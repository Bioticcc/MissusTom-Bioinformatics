import { useEffect, useRef } from "react";
import { EditorState } from "@codemirror/state";
import { EditorView } from "@codemirror/view";
import { StreamLanguage } from "@codemirror/language";
import { basicSetup } from "codemirror";
import { python } from "@codemirror/lang-python";
import { groovy } from "@codemirror/legacy-modes/mode/groovy";
import { r } from "@codemirror/legacy-modes/mode/r";
import { shell } from "@codemirror/legacy-modes/mode/shell";

type SourceEditorProps = {
  value: string;
  path: string;
  editable: boolean;
  onChange: (value: string) => void;
};

function languageFor(path: string) {
  if (path.endsWith(".md")) return [];
  if (path.endsWith(".py")) return python();
  if (path.endsWith(".R")) return StreamLanguage.define(r);
  if (path.endsWith(".sh") || path.endsWith("run_with_timeout")) return StreamLanguage.define(shell);
  return StreamLanguage.define(groovy);
}

/** CodeMirror owns its DOM and is recreated only for a file or mode change. */
export function SourceEditor({ value, path, editable, onChange }: SourceEditorProps) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView>();
  const changeHandler = useRef(onChange);
  changeHandler.current = onChange;

  useEffect(() => {
    if (!host.current) return;
    const state = EditorState.create({
      doc: value,
      extensions: [
        basicSetup,
        languageFor(path),
        EditorState.readOnly.of(!editable),
        EditorView.editable.of(editable),
        EditorView.updateListener.of((update) => {
          if (update.docChanged) changeHandler.current(update.state.doc.toString());
        }),
      ],
    });
    const instance = new EditorView({ state, parent: host.current });
    view.current = instance;
    return () => { instance.destroy(); if (view.current === instance) view.current = undefined; };
  // `value` changes only when a file is loaded, saved, or cancelled. Keystrokes stay in CodeMirror.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, editable]);

  useEffect(() => {
    const instance = view.current;
    if (!instance || instance.state.doc.toString() === value) return;
    instance.dispatch({ changes: { from: 0, to: instance.state.doc.length, insert: value } });
  }, [value]);

  return <div className={editable ? "code-mirror editing" : "code-mirror"} ref={host} />;
}
