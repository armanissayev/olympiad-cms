"""Bounded, descriptive editing review cues; never a plagiarism or source verdict."""
from collections import deque
from math import isfinite
from .telemetry_schema import DOCUMENT_TYPES

THRESHOLDS = {
    'largeInsertCharacters': 200,
    'rapidInputCharacters': 1000,
    'rapidInputWindowSeconds': 10,
    'longPauseSeconds': 120,
    'slowEditingMinimumSeconds': 300,
    'slowEditingMinimumChanges': 10,
    'slowEditingCharactersPerMinute': 20,
}
REVIEW_NOTICE = ('Review markers describe recorded activity, not proof of plagiarism. '
                 'Inserted editor text is recorded; raw clipboard contents outside the editor and paste source websites/apps are not collected, so paste provenance is unknown.')


def units(text):
    return len(text.encode('utf-16-le', errors='surrogatepass')) // 2


def marker(kind, label, detail):
    return {'kind': kind, 'label': label, 'detail': detail}


def group_file_events(events, interval_seconds):
    """Collapse relevant file activity into occupied fixed-duration intervals.

    Key-up, cursor, focus, navigation and execution noise never enters the output.
    The input is already restricted to one scoped file and a permitted prefix.
    Keyboard counts count source transactions correlated with a recorded key-down,
    rather than counting navigation/modifier keys as code writing.
    """
    buckets, transactions, rolling = {}, {}, deque()
    previous_edit = None
    rolling_total = 0
    last_rapid = float('-inf')
    typed_characters, typed_changes, first_typed, last_typed = 0, 0, None, None
    pasted = {event.get('payload', {}).get('transactionId') for event in events
              if event.get('eventType') == 'PASTE' and isinstance(event.get('payload'), dict)}
    pasted.discard(None)
    for event in events:
        kind, payload = event.get('eventType'), event.get('payload', {})
        offset, sequence = event.get('monotonicOffsetMs'), event.get('sequence')
        if (not isinstance(payload, dict) or type(sequence) is not int or sequence < 1
                or isinstance(offset, bool) or not isinstance(offset, (int, float))
                or not isfinite(offset) or offset < 0):
            continue
        if kind not in DOCUMENT_TYPES | {'PASTE', 'KEY_DOWN', 'FILE_CREATED', 'WORKSPACE_RECONCILED'}:
            continue
        copy_shortcut = (kind == 'KEY_DOWN' and payload.get('key') in ('c', 'C')
                         and (payload.get('ctrl') is True or payload.get('meta') is True)
                         and not payload.get('alt') and not payload.get('shift'))
        if kind == 'KEY_DOWN' and not copy_shortcut:
            continue
        bucket = int(offset // (interval_seconds * 1000))
        point = buckets.setdefault(bucket, {'sequence': sequence, 'offsetMs': offset,
            'startOffsetMs': bucket * interval_seconds * 1000, 'endOffsetMs': (bucket + 1) * interval_seconds * 1000,
            'timestamp': event.get('clientTimestamp'), 'kind': 'editing', 'inserted': 0, 'deleted': 0,
            'editCount': 0, 'keyboardInputs': 0, 'markers': []})
        point.update(sequence=sequence, offsetMs=offset, timestamp=event.get('clientTimestamp'))
        def add(value):
            # Repeated paste/copy events in one interval are represented once, with counts in metrics.
            if not any(existing['kind'] == value['kind'] for existing in point['markers']):
                point['markers'].append(value)
        if copy_shortcut:
            add(marker('copy-shortcut', 'Copy shortcut', 'Ctrl/Cmd+C was pressed in the editor. Clipboard transfer or destination is not observable.'))
        elif kind == 'PASTE':
            transaction = transactions.get(payload.get('transactionId'))
            detail = ('The editor recorded a paste' + (f' associated with {transaction} inserted characters' if transaction is not None else '')
                      + '. The source is unknown; the browser recording does not identify a source website/app or whether it is trusted.')
            add(marker('paste', 'Paste · source unknown', detail))
        elif kind in ('FILE_CREATED', 'WORKSPACE_RECONCILED'):
            add(marker('context', 'File creation / restored state', 'This is a file creation, import or restored workspace state, not evidence of typing or paste.'))
        else:
            changes = payload.get('changes', [])
            if not isinstance(changes, list):
                continue
            inserted = sum(units(change['insertedText']) for change in changes if isinstance(change, dict) and isinstance(change.get('insertedText'), str))
            deleted = sum(change['deletedLength'] for change in changes if isinstance(change, dict) and type(change.get('deletedLength')) is int and change['deletedLength'] >= 0)
            point['inserted'] += inserted
            point['deleted'] += deleted
            point['editCount'] += 1
            transaction_id = payload.get('transactionId')
            if isinstance(transaction_id, str):
                transactions[transaction_id] = inserted
            keyboard = isinstance(payload.get('inputEventId'), str)
            point['keyboardInputs'] += int(keyboard)
            ordinary = payload.get('origin') == 'editor' and kind not in ('UNDO', 'REDO')
            if not ordinary:
                add(marker('context', 'Undo / redo / generated change', 'This edit is undo, redo or programmatic activity; it is excluded from large/rapid/slow writing cues.'))
                continue
            if previous_edit is not None and offset - previous_edit >= THRESHOLDS['longPauseSeconds'] * 1000:
                seconds = round((offset - previous_edit) / 1000)
                add(marker('long-pause', 'Long pause', f'{seconds} seconds between recorded source edits. Thinking, reading or working elsewhere can explain this.'))
            previous_edit = offset
            if inserted >= THRESHOLDS['largeInsertCharacters']:
                add(marker('large-insert', 'Large insertion', f'{inserted} characters inserted in one editor transaction. Paste, completion and formatting are possible explanations; only a separate paste event confirms a paste.'))
            while rolling and offset - rolling[0][0] > THRESHOLDS['rapidInputWindowSeconds'] * 1000:
                rolling_total -= rolling.popleft()[1]
            rolling.append((offset, inserted))
            rolling_total += inserted
            total = rolling_total
            if (len(rolling) >= 2 and total >= THRESHOLDS['rapidInputCharacters']
                    and offset - last_rapid >= THRESHOLDS['rapidInputWindowSeconds'] * 1000):
                add(marker('rapid-input', 'Rapid source growth', f'{total} inserted characters across editor changes within {THRESHOLDS["rapidInputWindowSeconds"]} seconds. Generated edits and completions can also cause this.'))
                last_rapid = offset
            if keyboard and transaction_id not in pasted:
                typed_characters += inserted
                typed_changes += 1
                first_typed = offset if first_typed is None else first_typed
                last_typed = offset
    points = [buckets[key] for key in sorted(buckets)]
    if points and first_typed is not None and last_typed is not None:
        elapsed = (last_typed - first_typed) / 1000
        if elapsed >= THRESHOLDS['slowEditingMinimumSeconds'] and typed_changes >= THRESHOLDS['slowEditingMinimumChanges']:
            rate = typed_characters * 60 / elapsed
            if rate < THRESHOLDS['slowEditingCharactersPerMinute']:
                points[-1]['markers'].append(marker('slow-editing', 'Slow recorded editing',
                    f'{rate:.1f} inserted characters/minute across {elapsed / 60:.1f} elapsed minutes and {typed_changes} keyboard-linked edits. Elapsed time includes pauses; this is context, not a misconduct finding.'))
    for point in points:
        point['label'] = (f'{point["editCount"]} edit' + ('' if point['editCount'] == 1 else 's')
                          + f' · +{point["inserted"]} / −{point["deleted"]}')
    return points
