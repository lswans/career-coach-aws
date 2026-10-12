import { useEffect, useRef, useState } from 'react';
import { buildProfile, isNormalizedError } from '../api/client';
import type { BuildEvent, BuildProgress, Health, HealthRules, ProfileResponse } from '../api/types';
import { BuildStatus, initialStages, type StageMap } from '../components/BuildStatus';
import { trimmedLength } from '../lib/format';

type Step = 1 | 2 | 3;

const PASTE_LABELS = ['Achievements', 'Certifications', 'Projects', 'Anything else'] as const;
type PasteLabel = (typeof PASTE_LABELS)[number];

/** Used until GET /api/health answers. The server always enforces the real rules. */
const DEFAULT_RULES: HealthRules = {
  min_goal_chars: 200,
  min_doc_chars: 50,
  max_files: 10,
  max_file_mb: 5,
  allowed_extensions: ['.pdf', '.docx', '.txt', '.md'],
};

const pasteId = (label: PasteLabel) => `paste-${label.toLowerCase().replace(/\s+/g, '-')}`;

function extensionOf(name: string): string {
  const i = name.lastIndexOf('.');
  return i >= 0 ? name.slice(i).toLowerCase() : '';
}

/** Why a file can't be sent, or null if it is fine. */
function fileProblem(file: File, rules: HealthRules): string | null {
  if (!rules.allowed_extensions.includes(extensionOf(file.name))) {
    return `Unsupported type (allowed: ${rules.allowed_extensions.join(', ')})`;
  }
  if (file.size > rules.max_file_mb * 1024 * 1024) {
    return `Too large (max ${rules.max_file_mb} MB)`;
  }
  return null;
}

export function SetupWizard({
  userId,
  health,
  initialGoals,
  onDone,
  onCancel,
}: {
  userId: string;
  health: Health | null;
  initialGoals?: string;
  onDone: (res: ProfileResponse) => void;
  onCancel?: () => void;
}) {
  const rules = health?.rules ?? DEFAULT_RULES;

  const [step, setStep] = useState<Step>(1);
  const [files, setFiles] = useState<File[]>([]);
  const [fileNotice, setFileNotice] = useState<string | null>(null);
  const [pastes, setPastes] = useState<Record<PasteLabel, string>>({
    Achievements: '',
    Certifications: '',
    Projects: '',
    'Anything else': '',
  });
  const [goals, setGoals] = useState(initialGoals ?? '');
  const [dragging, setDragging] = useState(false);

  const [building, setBuilding] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [stages, setStages] = useState<StageMap>(initialStages);
  const [progress, setProgress] = useState<BuildProgress | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [serverError, setServerError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  // Count seconds while the model works.
  useEffect(() => {
    if (!building) return;
    const started = Date.now();
    setElapsed(0);
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(id);
  }, [building]);

  // What the user has given us so far.
  const problems = files.map((f) => fileProblem(f, rules));
  const validFiles = files.filter((_, i) => problems[i] === null);
  const badFiles = files.length - validFiles.length;
  const pasteChars = PASTE_LABELS.reduce((sum, l) => sum + trimmedLength(pastes[l]), 0);
  const entries = PASTE_LABELS.filter((l) => pastes[l].trim()).map((l) => ({
    label: l,
    text: pastes[l].trim(),
  }));
  const hasDocs = validFiles.length > 0 || pasteChars >= rules.min_doc_chars;
  const goalLen = trimmedLength(goals);
  const goalsOk = goalLen >= rules.min_goal_chars;
  const canBuild = hasDocs && goalsOk && badFiles === 0;

  // Say exactly what is still missing, instead of only disabling the button.
  const missing: string[] = [];
  if (!hasDocs) {
    missing.push(
      `Add at least one file, or paste at least ${rules.min_doc_chars} characters of text in step 1`,
    );
  }
  if (badFiles > 0) missing.push('Remove the files marked unsupported or too large in step 1');
  if (!goalsOk) {
    const need = rules.min_goal_chars - goalLen;
    missing.push(`Write ${need} more character${need === 1 ? '' : 's'} of goals`);
  }

  function addFiles(list: FileList | File[]) {
    const incoming = Array.from(list);
    const room = Math.max(0, rules.max_files - files.length);
    setFileNotice(
      incoming.length > room
        ? `Only ${rules.max_files} files are allowed, so ${incoming.length - room} were skipped.`
        : null,
    );
    setFiles((prev) => [...prev, ...incoming].slice(0, rules.max_files));
  }

  function removeFile(idx: number) {
    setFiles((prev) => prev.filter((_, i) => i !== idx));
    setFileNotice(null);
  }

  function onBuildEvent(evt: BuildEvent) {
    if (evt.type === 'stage') {
      setStages((s) => ({ ...s, [evt.stage]: { state: evt.state, detail: evt.detail } }));
    } else if (evt.type === 'progress') {
      setProgress(evt);
    }
  }

  async function build() {
    setServerError(null);
    setFieldErrors({});
    setStages(initialStages());
    setProgress(null);
    const controller = new AbortController();
    abortRef.current = controller;
    setBuilding(true);
    setStep(3);
    try {
      const res = await buildProfile(
        userId,
        { files: validFiles, entries, goals: goals.trim() },
        onBuildEvent,
        controller.signal,
      );
      onDone(res);
    } catch (e) {
      setBuilding(false);
      if (controller.signal.aborted) {
        setStep(2); // the user pressed Cancel
      } else if (isNormalizedError(e) && e.status === 422 && e.fields) {
        setFieldErrors(e.fields);
        // Go back to the step that owns the problem.
        setStep(e.fields.documents || e.fields.files ? 1 : 2);
      } else {
        setServerError(isNormalizedError(e) ? e.message : 'Something went wrong. Please try again.');
      }
    } finally {
      abortRef.current = null;
    }
  }

  return (
    <main className="app">
      <ol className="stepper" aria-label="Setup steps">
        <li aria-current={step === 1 ? 'step' : undefined}>
          <span className="num">1</span> Dump your docs
        </li>
        <li aria-current={step === 2 ? 'step' : undefined}>
          <span className="num">2</span> Your career goals
        </li>
        <li aria-current={step === 3 ? 'step' : undefined}>
          <span className="num">3</span> Building your coach
        </li>
      </ol>

      {step === 1 && (
        <section className="card" aria-labelledby="step1-title">
          <h2 id="step1-title">Dump your docs</h2>
          <p className="muted">
            Add your resume, plus anything else about your achievements, certifications and
            projects.
          </p>
          {initialGoals !== undefined && (
            <p className="chip chip-warn" role="note">
              Your coach does not keep copies of your files. Add your documents again, plus
              anything new since last time.
            </p>
          )}
          <div
            className={`dropzone${dragging ? ' drag' : ''}`}
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              addFiles(e.dataTransfer.files);
            }}
          >
            <p>Drag and drop files here, or</p>
            <button type="button" className="btn" onClick={() => fileInputRef.current?.click()}>
              Choose files
            </button>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept={rules.allowed_extensions.join(',')}
              className="visually-hidden"
              tabIndex={-1}
              aria-hidden="true"
              aria-label="Choose files"
              onChange={(e) => {
                if (e.target.files) addFiles(e.target.files);
                e.target.value = ''; // lets you pick the same file again after removing it
              }}
            />
            <p className="counter">
              Allowed: {rules.allowed_extensions.join(', ')} · up to {rules.max_files} files ·{' '}
              {rules.max_file_mb} MB each
            </p>
          </div>

          {files.length > 0 && (
            <ul className="filelist" aria-label="Files to send">
              {files.map((f, i) => (
                <li key={`${f.name}-${i}`}>
                  <span className="fname">{f.name}</span>
                  <span className="counter">{Math.max(1, Math.round(f.size / 1024))} KB</span>
                  {problems[i] && <span className="chip chip-err">{problems[i]}</span>}
                  <button
                    type="button"
                    className="btn btn-sm"
                    onClick={() => removeFile(i)}
                    aria-label={`Remove ${f.name}`}
                  >
                    Remove
                  </button>
                </li>
              ))}
            </ul>
          )}
          {fileNotice && <p className="missing">{fileNotice}</p>}
          {fieldErrors.files && <p className="missing">{fieldErrors.files}</p>}
          {fieldErrors.documents && <p className="missing">{fieldErrors.documents}</p>}

          <h3>Paste anything you want the coach to know</h3>
          {PASTE_LABELS.map((label) => (
            <div className="field" key={label}>
              <label htmlFor={pasteId(label)}>{label}</label>
              <textarea
                id={pasteId(label)}
                value={pastes[label]}
                onChange={(e) => setPastes((p) => ({ ...p, [label]: e.target.value }))}
              />
            </div>
          ))}
          <p className="counter">
            Pasted text: {pasteChars} characters (at least {rules.min_doc_chars} if you add no
            files)
          </p>

          <div className="row">
            {onCancel && (
              <button type="button" className="btn" onClick={onCancel}>
                Cancel
              </button>
            )}
            <button type="button" className="btn btn-primary" onClick={() => setStep(2)}>
              Next: goals
            </button>
          </div>
        </section>
      )}

      {step === 2 && (
        <section className="card" aria-labelledby="step2-title">
          <h2 id="step2-title">Your career goals</h2>
          <p className="muted">
            What role do you want, by when, and why? What do you want to learn on the way?
          </p>
          <div className="field">
            <label htmlFor="goals">Career goals</label>
            <textarea
              id="goals"
              value={goals}
              style={{ minHeight: 160 }}
              onChange={(e) => setGoals(e.target.value)}
              aria-describedby="goal-counter"
            />
            <p id="goal-counter" className={`counter${goalsOk ? ' ok' : ''}`}>
              {goalLen} / {rules.min_goal_chars} characters minimum
            </p>
          </div>
          {fieldErrors.goals && <p className="missing">{fieldErrors.goals}</p>}

          {missing.length > 0 && (
            <ul className="missing" aria-label="Still needed before building">
              {missing.map((m) => (
                <li key={m}>{m}</li>
              ))}
            </ul>
          )}

          <div className="row">
            <button type="button" className="btn" onClick={() => setStep(1)}>
              Back
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => void build()}
              disabled={!canBuild}
            >
              Build my coach
            </button>
          </div>
        </section>
      )}

      {step === 3 && (
        <section className="card" aria-labelledby="step3-title">
          <h2 id="step3-title">Building your coach</h2>
          {building ? (
            <>
              <div className="spread">
                <p className="muted">
                  {health?.provider === 'ollama'
                    ? 'This usually takes 1 to 2 minutes on a laptop CPU.'
                    : 'This usually takes about 30 seconds.'}
                </p>
                <span className="counter" role="timer" aria-label="Seconds elapsed">
                  {elapsed}s
                </span>
              </div>
              <BuildStatus stages={stages} progress={progress} />
              <button type="button" className="btn" onClick={() => abortRef.current?.abort()}>
                Cancel
              </button>
            </>
          ) : (
            <div role="alert">
              <p className="missing">{serverError ?? 'Something went wrong.'}</p>
              <div className="row">
                <button type="button" className="btn btn-primary" onClick={() => void build()}>
                  Retry
                </button>
                <button type="button" className="btn" onClick={() => setStep(2)}>
                  Back to edit
                </button>
              </div>
            </div>
          )}
        </section>
      )}
    </main>
  );
}
