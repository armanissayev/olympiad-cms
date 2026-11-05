"""Review cues describe actual editor observations without inventing provenance."""
from copy import deepcopy
from math import nan
from app.history_analysis import group_file_events


def edit(sequence, at, text='x', kind='TEXT_INSERT', keyboard=True, origin='editor', deleted=0):
    return {'sequence': sequence, 'monotonicOffsetMs': at, 'clientTimestamp': '2026-11-05T00:00:00Z',
            'eventType': kind, 'payload': {'transactionId': f'transaction-{sequence}',
                'inputEventId': f'key-{sequence}' if keyboard else None, 'origin': origin,
                'changes': [{'insertedText': text, 'deletedLength': deleted}]}}


def passive(sequence, at, kind, payload=None):
    return {'sequence': sequence, 'monotonicOffsetMs': at, 'clientTimestamp': '2026-11-05T00:00:00Z',
            'eventType': kind, 'payload': payload or {}}


def kinds(points):
    return [value['kind'] for point in points for value in point['markers']]


def test_occupied_intervals_hide_raw_key_cursor_focus_execution_and_count_linked_source_changes():
    events=[passive(1,1,'KEY_DOWN',{'key':'a'}),edit(2,2),passive(3,3,'CURSOR_MOVED'),
            passive(4,4,'KEY_UP'),passive(5,5,'RUN_STARTED'),passive(6,6,'EDITOR_FOCUS'),
            edit(7,4999,'ab'),edit(8,5000,'c',keyboard=False)]
    points=group_file_events(events,5)
    assert [point['sequence'] for point in points]==[7,8]
    assert [(point['editCount'],point['keyboardInputs'],point['inserted']) for point in points]==[(2,2,3),(1,0,1)]
    assert [point['startOffsetMs'] for point in points]==[0,5000]


def test_unicode_and_multicursor_metrics_follow_monaco_utf16_offsets():
    event=edit(1,0,'😀Ω',deleted=2)
    event['payload']['changes'].append({'insertedText':'你好','deletedLength':1})
    point=group_file_events([event],5)[0]
    assert (point['inserted'],point['deleted'],point['editCount'])==(5,3,1)


def test_paste_is_observed_separately_from_large_insert_and_source_is_never_claimed():
    inserted=edit(1,100,'x'*250,keyboard=False)
    paste=passive(2,110,'PASTE',{'transactionId':'transaction-1'})
    points=group_file_events([inserted,paste],5)
    assert set(kinds(points))=={'large-insert','paste'}
    cue=next(value for value in points[0]['markers'] if value['kind']=='paste')
    assert 'unknown' in cue['label'] and '250' in cue['detail']
    assert 'does not identify' in cue['detail']
    assert 'paste' not in kinds(group_file_events([inserted],5))


def test_copy_shortcut_reports_only_shortcut_and_not_clipboard_transfer():
    points=group_file_events([passive(1,0,'KEY_DOWN',{'key':'c','ctrl':True}),
                              passive(2,5,'KEY_DOWN',{'key':'C','meta':True}),
                              passive(3,9,'KEY_DOWN',{'key':'c','ctrl':True,'alt':True})],5)
    assert kinds(points)==['copy-shortcut']
    assert points[0]['editCount']==0
    assert 'not observable' in points[0]['markers'][0]['detail']


def test_large_insert_threshold_and_repeat_pastes_in_interval_do_not_duplicate_cues():
    assert kinds(group_file_events([edit(1,0,'x'*199)],1))==[]
    points=group_file_events([edit(1,0,'x'*200),passive(2,1,'PASTE'),passive(3,2,'PASTE')],1)
    assert kinds(points)==['large-insert','paste']


def test_rapid_growth_uses_ten_second_window_across_intervals_and_has_explicit_threshold():
    assert 'rapid-input' in kinds(group_file_events([edit(1,0,'a'*500),edit(2,10000,'b'*500)],1))
    assert 'rapid-input' not in kinds(group_file_events([edit(1,0,'a'*500),edit(2,10001,'b'*500)],1))
    assert 'rapid-input' not in kinds(group_file_events([edit(1,0,'a'*1000)],1))


def test_undo_redo_and_programmatic_changes_keep_context_without_growth_or_slow_cues():
    events=[edit(1,0,'x'*1000,kind='UNDO'),edit(2,5,'y'*1000,kind='REDO'),
            edit(3,6,'z'*1000,origin='programmatic')]
    points=group_file_events(events,1)
    assert set(kinds(points))=={'context'}
    assert points[0]['inserted']==3000 and points[0]['editCount']==3


def test_long_pause_threshold_is_elapsed_time_and_not_an_authorship_accusation():
    assert 'long-pause' not in kinds(group_file_events([edit(1,0),edit(2,119999)],5))
    points=group_file_events([edit(1,0),edit(2,120000)],5)
    cue=next(value for point in points for value in point['markers'] if value['kind']=='long-pause')
    assert '120 seconds' in cue['detail'] and 'Thinking' in cue['detail']


def test_slow_writing_needs_sustained_keyboard_linked_changes_not_sparse_passive_events():
    events=[edit(index+1,index*30000) for index in range(11)]
    points=group_file_events(events,30)
    assert 'slow-editing' in kinds(points)
    cue=points[-1]['markers'][-1]
    assert 'includes pauses' in cue['detail'] and 'not a misconduct' in cue['detail']
    assert 'slow-editing' not in kinds(group_file_events([edit(1,0),edit(2,600000)],30))
    unlinked=deepcopy(events)
    for event in unlinked:event['payload']['inputEventId']=None
    assert 'slow-editing' not in kinds(group_file_events(unlinked,30))


def test_invalid_activity_timing_is_omitted_without_nonfinite_output():
    events=[edit(1,nan),edit(2,-1),edit(3,True),edit(4,1)]
    points=group_file_events(events,5)
    assert len(points)==1 and points[0]['sequence']==4 and points[0]['editCount']==1


def test_explicit_paste_transactions_are_not_counted_as_slow_keyboard_writing():
    events=[]
    for index in range(11):
        sequence=index*2+1
        events.extend([edit(sequence,index*30000),passive(sequence+1,index*30000+1,'PASTE',{'transactionId':f'transaction-{sequence}'})])
    points=group_file_events(events,30)
    assert 'paste' in kinds(points) and 'slow-editing' not in kinds(points)
