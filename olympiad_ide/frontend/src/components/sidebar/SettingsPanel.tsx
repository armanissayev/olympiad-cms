import { Keyboard, RotateCcw } from 'lucide-react'
import { defaultSettings, useWorkspaceStore } from '../../store/workspaceStore'
import type { EditorSettings } from '../../types/workspace'

const shortcuts = [
  ['Quick Open', 'Ctrl/Cmd + P'],
  ['Toggle Explorer', 'Ctrl/Cmd + B'],
  ['Toggle Panel', 'Ctrl/Cmd + J'],
  ['Split Editor', 'Ctrl/Cmd + \\'],
  ['Close Tab', 'Ctrl/Cmd + W'],
  ['Settings', 'Ctrl/Cmd + ,'],
  ['Zen Mode', 'Ctrl/Cmd + K, Z'],
  ['Find / Replace', 'Ctrl/Cmd + F / H'],
]

export function SettingsPanel() {
  const settings = useWorkspaceStore((state) => state.settings)
  const update = useWorkspaceStore((state) => state.updateSettings)

  return (
    <aside className="sidebar-panel">
      <div className="sidebar-title flex items-center justify-between">
        Settings
        <button className="tiny-icon-button" onClick={() => update(defaultSettings)} title="Reset settings" aria-label="Reset settings">
          <RotateCcw className="h-3.5 w-3.5" />
        </button>
      </div>
      <div className="settings-scroll">
        <SettingSelect
          label="Color Theme"
          value={settings.theme}
          onChange={(value) => update({ theme: value as EditorSettings['theme'] })}
          options={[
            ['dark-modern', 'Dark Modern'],
            ['light', 'Light'],
            ['high-contrast', 'High Contrast'],
          ]}
        />
        <SettingNumber label="Font Size" value={settings.fontSize} min={10} max={28} onChange={(fontSize) => update({ fontSize })} />
        <label className="setting-field">
          <span>Font Family</span>
          <input value={settings.fontFamily} onChange={(event) => update({ fontFamily: event.target.value })} />
        </label>
        <SettingNumber label="Tab Size" value={settings.tabSize} min={1} max={8} onChange={(tabSize) => update({ tabSize })} />
        <SettingSelect
          label="Indentation"
          value={settings.insertSpaces ? 'spaces' : 'tabs'}
          onChange={(value) => update({ insertSpaces: value === 'spaces' })}
          options={[
            ['spaces', 'Spaces'],
            ['tabs', 'Tabs'],
          ]}
        />
        <SettingSelect
          label="Word Wrap"
          value={settings.wordWrap}
          onChange={(value) => update({ wordWrap: value as EditorSettings['wordWrap'] })}
          options={[
            ['off', 'Off'],
            ['on', 'On'],
          ]}
        />
        <SettingToggle label="Minimap" checked={settings.minimap} onChange={(minimap) => update({ minimap })} />
        <SettingSelect
          label="Auto-closing Brackets"
          value={settings.autoClosingBrackets}
          onChange={(value) => update({ autoClosingBrackets: value as EditorSettings['autoClosingBrackets'] })}
          options={[
            ['always', 'Always'],
            ['never', 'Never'],
          ]}
        />
        <SettingSelect
          label="Line Numbers"
          value={settings.lineNumbers}
          onChange={(value) => update({ lineNumbers: value as EditorSettings['lineNumbers'] })}
          options={[
            ['on', 'On'],
            ['relative', 'Relative'],
            ['off', 'Off'],
          ]}
        />
        <SettingSelect
          label="Cursor Style"
          value={settings.cursorStyle}
          onChange={(value) => update({ cursorStyle: value as EditorSettings['cursorStyle'] })}
          options={[
            ['line', 'Line'],
            ['block', 'Block'],
            ['underline', 'Underline'],
          ]}
        />
        <SettingSelect
          label="Server Auto Save (local recovery is always on)"
          value={settings.autoSave}
          onChange={(value) => update({ autoSave: value as EditorSettings['autoSave'] })}
          options={[
            ['afterDelay', 'After Delay'],
            ['off', 'Manual (Ctrl/Cmd+S)'],
          ]}
        />
        <SettingSelect
          label="Render Whitespace"
          value={settings.renderWhitespace}
          onChange={(value) => update({ renderWhitespace: value as EditorSettings['renderWhitespace'] })}
          options={[
            ['none', 'None'],
            ['selection', 'Selection'],
            ['all', 'All'],
          ]}
        />

        <div className="mt-5 border-t border-[var(--border)] pt-4">
          <div className="mb-3 flex items-center gap-2 text-xs font-semibold text-[var(--fg-strong)]">
            <Keyboard className="h-4 w-4" /> Keyboard shortcuts
          </div>
          {shortcuts.map(([label, keys]) => (
            <div className="shortcut-row" key={label}>
              <span>{label}</span>
              <kbd>{keys}</kbd>
            </div>
          ))}
        </div>
      </div>
    </aside>
  )
}

interface SelectProps {
  label: string
  value: string
  options: [string, string][]
  onChange: (value: string) => void
}

function SettingSelect({ label, value, options, onChange }: SelectProps) {
  return (
    <label className="setting-field">
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        {options.map(([optionValue, optionLabel]) => <option value={optionValue} key={optionValue}>{optionLabel}</option>)}
      </select>
    </label>
  )
}

interface NumberProps {
  label: string
  value: number
  min: number
  max: number
  onChange: (value: number) => void
}

function SettingNumber({ label, value, min, max, onChange }: NumberProps) {
  return (
    <label className="setting-field">
      <span>{label}</span>
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        onChange={(event) => onChange(Math.min(max, Math.max(min, Number(event.target.value))))}
      />
    </label>
  )
}

function SettingToggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (checked: boolean) => void }) {
  return (
    <label className="setting-toggle">
      <span>{label}</span>
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
    </label>
  )
}
