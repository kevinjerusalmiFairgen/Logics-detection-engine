import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

/** Empty = same origin (UI from `uvicorn` static dist, or Vite dev via proxy). Override with VITE_API_BASE. */
const _rawApi = import.meta.env.VITE_API_BASE;
const API_BASE =
  typeof _rawApi === "string" && _rawApi.trim() !== "" ? _rawApi.trim() : "";
const ACTIVE_PROJECT_KEY = "logic-platform.activeProjectId";

type RunProgress = {
  run_id: string;
  status: "created" | "running" | "complete" | "failed" | "missing";
  percent: number;
  current_step?: number | null;
  current_step_label?: string | null;
  message: string;
};

type Project = {
  run_id: string;
  artifacts: Record<string, string>;
  metadata?: {
    project_name?: string;
    pdf_filename?: string;
    data_filename?: string;
    filename?: string;
    engine?: string;
  };
  progress?: RunProgress;
};

type ApiResult = Project & {
  status?: string;
  message?: string;
  missing_columns?: string[];
  warnings?: Array<{ row_id: string; message: string }>;
  report?: unknown;
  logics?: unknown;
};

function projectName(project: Project) {
  if (project.metadata?.project_name) {
    return project.metadata.project_name;
  }
  const files = [project.metadata?.pdf_filename, project.metadata?.data_filename].filter(Boolean);
  return files.length > 0 ? files.join(" + ") : project.metadata?.filename ?? project.run_id;
}

function fileStem(filename: string) {
  return filename.replace(/\.[^/.]+$/, "");
}

const ARTIFACT_DOWNLOAD_NAMES: Record<string, string> = {
  questionnaire_final: "questionnaire.json",
  structure_json: "structure.json",
  fairset_report: "fairset_report.json",
  logics_json: "logics.json",
};

function parseContentDispositionFilename(header: string | null): string | null {
  if (!header) {
    return null;
  }
  const utf8 = /filename\*=UTF-8''([^;\n]+)/i.exec(header);
  if (utf8?.[1]) {
    try {
      return decodeURIComponent(utf8[1].trim());
    } catch {
      return utf8[1].trim();
    }
  }
  const quoted = /filename="([^"]+)"/i.exec(header);
  if (quoted?.[1]) {
    return quoted[1];
  }
  const sq = /filename='([^']+)'/i.exec(header);
  if (sq?.[1]) {
    return sq[1];
  }
  const plain = /filename=([^;\s]+)/i.exec(header);
  if (plain?.[1]) {
    return plain[1].replace(/^["']|["']$/g, "");
  }
  return null;
}

function FileInput({
  label,
  accept,
  hint,
  onChange,
}: {
  label: string;
  accept: string;
  hint?: string;
  onChange: (file: File | null) => void;
}) {
  const [filename, setFilename] = useState("");

  return (
    <label className="field">
      <span>{label}</span>
      {hint ? <span className="optionalHint">{hint}</span> : null}
      <span className="filePicker">
        <input
          type="file"
          accept={accept}
          onChange={(event) => {
            const file = event.target.files?.[0] ?? null;
            setFilename(file?.name ?? "");
            onChange(file);
          }}
        />
        <span className={filename ? "fileName" : "filePlaceholder"}>{filename || "No file selected"}</span>
        <span className="fileButton">Select</span>
      </span>
    </label>
  );
}

function ProgressStatus({
  busy,
  progress,
}: {
  busy: string;
  progress: RunProgress | null;
}) {
  if (progress) {
    const pct =
      typeof progress.percent === "number" && Number.isFinite(progress.percent)
        ? Math.min(100, Math.max(0, progress.percent))
        : 0;
    return (
      <div className="miniProgress">
        <div>
          <strong>{pct}%</strong>
          <span>{progress.message ?? ""}</span>
        </div>
        <div className="progressTrack">
          <div className={`progressFill ${progress.status ?? ""}`} style={{ width: `${pct}%` }} />
        </div>
      </div>
    );
  }

  if (!busy) {
    return null;
  }

  return (
    <div className="miniProgress">
      <div>
        <strong>Working</strong>
        <span>{busy}</span>
      </div>
      <div className="progressTrack">
        <div className="progressFill indeterminate" />
      </div>
    </div>
  );
}

function App() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProject, setSelectedProject] = useState<ApiResult | null>(null);
  const [progress, setProgress] = useState<RunProgress | null>(null);
  const [qnrFile, setQnrFile] = useState<File | null>(null);
  const [dataFile, setDataFile] = useState<File | null>(null);
  const [questionnaireJsonFile, setQuestionnaireJsonFile] = useState<File | null>(null);
  const [newFairsetOptional, setNewFairsetOptional] = useState<File | null>(null);
  const [fairsetForReview, setFairsetForReview] = useState<File | null>(null);
  const [projectNameInput, setProjectNameInput] = useState("");
  const [renameInput, setRenameInput] = useState("");
  const [workspaceMode, setWorkspaceMode] = useState<"new" | "project">("new");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const pollTimer = useRef<number | null>(null);
  const pendingFairsetRef = useRef<File | null>(null);
  const autoDownloadPackRef = useRef(false);

  function sleep(ms: number) {
    return new Promise<void>((resolve) => {
      window.setTimeout(resolve, ms);
    });
  }

  useEffect(() => {
    void loadProjects();
    const savedProjectId = window.localStorage.getItem(ACTIVE_PROJECT_KEY);
    if (savedProjectId) {
      void openProject(savedProjectId);
    }
    return stopPolling;
  }, []);

  async function downloadRunArtifact(project: Project, artifactKey: string) {
    setError("");
    const fallback = ARTIFACT_DOWNLOAD_NAMES[artifactKey] ?? `${artifactKey}.bin`;
    try {
      const res = await fetch(`${API_BASE}/runs/${project.run_id}/artifacts/${artifactKey}`);
      if (!res.ok) {
        let msg = `Download failed (${res.status})`;
        try {
          const j = (await res.json()) as { detail?: string };
          if (j.detail) {
            msg = j.detail;
          }
        } catch {
          /* ignore */
        }
        throw new Error(msg);
      }
      const name =
        parseContentDispositionFilename(res.headers.get("Content-Disposition")) ?? fallback;
      const blob = await res.blob();
      const obj = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = obj;
      a.download = name;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(obj);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Download failed.");
    }
  }

  function stopPolling() {
    if (pollTimer.current !== null) {
      window.clearInterval(pollTimer.current);
      pollTimer.current = null;
    }
  }

  async function loadProjects() {
    try {
      const response = await fetch(`${API_BASE}/runs`);
      if (!response.ok) {
        setError("Could not load previous projects.");
        return;
      }
      const body = (await response.json()) as { runs?: Project[] };
      // List every run dir: in-progress jobs often have empty `artifacts` here because
      // intermediates are stored as s1_*.json while the API only keys canonical outputs.
      setProjects(
        (body.runs ?? [])
          .filter(Boolean)
          .map((project) => ({ ...project, artifacts: project.artifacts ?? {} })),
      );
    } catch {
      setError(
        API_BASE
          ? `Could not reach the API at ${API_BASE}.`
          : "Could not reach the API. Start uvicorn on port 8000 (or run Vite dev so /runs is proxied).",
      );
    }
  }

  function projectListHint(project: Project) {
    const a = project.artifacts ?? {};
    if (a.fairset_report) return "reviewed";
    if (a.structure_json) return "ready";
    if (a.logics_json) return "extracting…";
    if (Object.keys(a).length > 0) return "…";
    return "starting…";
  }

  async function openProject(runId: string) {
    setError("");
    try {
      const response = await fetch(`${API_BASE}/runs/${runId}`);
      if (!response.ok) {
        setError("Could not open this project.");
        window.localStorage.removeItem(ACTIVE_PROJECT_KEY);
        return;
      }
      const body = (await response.json()) as ApiResult;
      if (!body.run_id) {
        setError("Invalid project response from API.");
        return;
      }
      setSelectedProject({
        ...body,
        artifacts: body.artifacts ?? {},
      });
      setProgress(body.progress ?? null);
      setRenameInput(projectName({ ...body, artifacts: body.artifacts ?? {} }));
      setWorkspaceMode("project");
      window.localStorage.setItem(ACTIVE_PROJECT_KEY, runId);
      if (body.progress?.status === "running" || body.progress?.status === "created") {
        startPolling(runId);
      }
    } catch {
      setError("Could not open this project.");
      window.localStorage.removeItem(ACTIVE_PROJECT_KEY);
    }
  }

  async function finalizeLogicsPipeline(runId: string) {
    const queuedFairset = pendingFairsetRef.current;
    pendingFairsetRef.current = null;
    const shouldDownloadPack = autoDownloadPackRef.current && !queuedFairset;
    autoDownloadPackRef.current = false;

    try {
      setError("");
      let runRes = await fetch(`${API_BASE}/runs/${runId}`);
      if (!runRes.ok) {
        throw new Error("Could not load run after pipeline.");
      }
      let proj = (await runRes.json()) as ApiResult;
      let arts = proj.artifacts ?? {};

      if (!arts.logics_json) {
        throw new Error("Pipeline finished but logics.json is missing.");
      }

      if (!arts.structure_json) {
        setBusy("Structure…");
        const sRes = await fetch(`${API_BASE}/runs/${runId}/fairset-structure`, { method: "POST" });
        if (!sRes.ok) {
          const detail = (await sRes.json().catch(() => ({}))) as { detail?: string };
          throw new Error(detail.detail ?? "Could not build structure.json.");
        }
        runRes = await fetch(`${API_BASE}/runs/${runId}`);
        proj = (await runRes.json()) as ApiResult;
        arts = proj.artifacts ?? {};
      }

      await openProject(runId);
      await loadProjects();

      if (queuedFairset) {
        setBusy("Fairset…");
        const fd = new FormData();
        fd.append("fairset_file", queuedFairset);
        const rv = await fetch(`${API_BASE}/runs/${runId}/fairset-review`, { method: "POST", body: fd });
        const reviewBody = (await rv.json()) as ApiResult;
        if (!rv.ok) {
          throw new Error(
            reviewBody.message ?? reviewBody.missing_columns?.join(", ") ?? "Fairset review failed.",
          );
        }
        const refreshed = await fetch(`${API_BASE}/runs/${runId}`);
        const refreshedProject = refreshed.ok ? ((await refreshed.json()) as ApiResult) : proj;
        setSelectedProject({
          ...reviewBody,
          artifacts: refreshedProject.artifacts ?? {},
          progress: refreshedProject.progress,
        });
        setNewFairsetOptional(null);
      } else if (shouldDownloadPack) {
        setBusy("Downloads…");
        if (arts.questionnaire_final) {
          await downloadRunArtifact(
            { run_id: runId, artifacts: arts, metadata: proj.metadata },
            "questionnaire_final",
          );
          await sleep(600);
        }
        runRes = await fetch(`${API_BASE}/runs/${runId}`);
        proj = (await runRes.json()) as ApiResult;
        arts = proj.artifacts ?? {};
        if (arts.structure_json) {
          await downloadRunArtifact(
            { run_id: runId, artifacts: arts, metadata: proj.metadata },
            "structure_json",
          );
        }
      }

      await loadProjects();
      await openProject(runId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not finish outputs.");
    } finally {
      setBusy("");
    }
  }

  function startPolling(runId: string) {
    stopPolling();
    async function tick() {
      const response = await fetch(`${API_BASE}/runs/${runId}/progress`);
      if (!response.ok) {
        return;
      }
      const nextProgress = (await response.json()) as RunProgress;
      setProgress(nextProgress);
      if (nextProgress.status === "complete" || nextProgress.status === "failed") {
        stopPolling();
        setBusy("");
        if (nextProgress.status === "failed") {
          pendingFairsetRef.current = null;
          autoDownloadPackRef.current = false;
        }
        await openProject(runId);
        await loadProjects();
        if (nextProgress.status === "complete") {
          await finalizeLogicsPipeline(runId);
        }
      }
    }
    void tick();
    pollTimer.current = window.setInterval(tick, 2500);
  }

  async function createProject() {
    if (!qnrFile || !dataFile) {
      setError("Upload a questionnaire PDF and a data file first.");
      return;
    }
    pendingFairsetRef.current = newFairsetOptional;
    autoDownloadPackRef.current = !newFairsetOptional;
    setBusy("Starting…");
    setProgress({ run_id: "", status: "created", percent: 5, message: "Starting extraction..." });
    setError("");
    const formData = new FormData();
    formData.append("questionnaire_pdf", qnrFile);
    formData.append("data_file", dataFile);
    formData.append("project_name", projectNameInput.trim() || fileStem(dataFile.name));

    try {
      const response = await fetch(`${API_BASE}/runs/logics/start?engine=manus`, {
        method: "POST",
        body: formData,
      });
      const body = (await response.json()) as ApiResult;
      if (!response.ok) {
        throw new Error(body.message ?? "Could not start extraction.");
      }
      const normalized = { ...body, artifacts: body.artifacts ?? {} };
      setSelectedProject(normalized);
      setProgress(body.progress ?? null);
      setRenameInput(projectName(normalized));
      setWorkspaceMode("project");
      window.localStorage.setItem(ACTIVE_PROJECT_KEY, body.run_id);
      await loadProjects();
      startPolling(body.run_id);
    } catch (caught) {
      setBusy("");
      pendingFairsetRef.current = null;
      autoDownloadPackRef.current = false;
      setError(caught instanceof Error ? caught.message : "Could not start extraction.");
    }
  }

  async function createStructureProject() {
    if (!questionnaireJsonFile) {
      setError("Upload a questionnaire JSON first.");
      return;
    }
    setBusy("Generating structure from questionnaire");
    setProgress(null);
    setError("");
    const formData = new FormData();
    formData.append("questionnaire_file", questionnaireJsonFile);
    formData.append(
      "project_name",
      projectNameInput.trim() || fileStem(questionnaireJsonFile.name),
    );

    try {
      const response = await fetch(`${API_BASE}/runs/structure/from-questionnaire`, {
        method: "POST",
        body: formData,
      });
      const body = (await response.json()) as ApiResult;
      if (!response.ok) {
        throw new Error(body.message ?? "Could not generate structure.");
      }
      const normalized = { ...body, artifacts: body.artifacts ?? {} };
      setSelectedProject(normalized);
      setProgress(body.progress ?? null);
      setRenameInput(projectName(normalized));
      setWorkspaceMode("project");
      window.localStorage.setItem(ACTIVE_PROJECT_KEY, body.run_id);
      await loadProjects();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not generate structure.");
    } finally {
      setBusy("");
    }
  }

  async function generateStructure() {
    if (!selectedProject) {
      return;
    }
    setBusy("Generating structure.json");
    setProgress(null);
    setError("");
    try {
      const response = await fetch(`${API_BASE}/runs/${selectedProject.run_id}/fairset-structure`, {
        method: "POST",
      });
      if (!response.ok) {
        const body = await response.json();
        throw new Error(body.detail ?? "Could not generate structure.json.");
      }
      await openProject(selectedProject.run_id);
      await loadProjects();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not generate structure.json.");
    } finally {
      setBusy("");
    }
  }

  async function renameProject() {
    if (!selectedProject) {
      return;
    }
    const nextName = renameInput.trim();
    if (!nextName) {
      setError("Project name cannot be empty.");
      return;
    }
    setBusy("Saving project name");
    setError("");
    try {
      const response = await fetch(`${API_BASE}/runs/${selectedProject.run_id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_name: nextName }),
      });
      const body = (await response.json()) as ApiResult;
      if (!response.ok) {
        throw new Error(body.message ?? "Could not rename project.");
      }
      const normalized = { ...body, artifacts: body.artifacts ?? {} };
      setSelectedProject(normalized);
      setRenameInput(projectName(normalized));
      await loadProjects();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not rename project.");
    } finally {
      setBusy("");
    }
  }

  async function reviewFairset() {
    if (!selectedProject) {
      return;
    }
    if (!fairsetForReview) {
      setError("Pick a Fairset file.");
      return;
    }
    setBusy("Fairset review");
    setProgress(null);
    setError("");
    const formData = new FormData();
    formData.append("fairset_file", fairsetForReview);
    try {
      const response = await fetch(`${API_BASE}/runs/${selectedProject.run_id}/fairset-review`, {
        method: "POST",
        body: formData,
      });
      const body = (await response.json()) as ApiResult;
      if (!response.ok) {
        throw new Error(body.message ?? body.missing_columns?.join(", ") ?? "Fairset review failed.");
      }
      const refreshed = await fetch(`${API_BASE}/runs/${selectedProject.run_id}`);
      const refreshedProject = refreshed.ok ? ((await refreshed.json()) as ApiResult) : selectedProject;
      const arts = refreshedProject.artifacts ?? {};
      setSelectedProject({ ...body, artifacts: arts, progress: refreshedProject.progress });
      setFairsetForReview(null);
      await loadProjects();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Fairset review failed.");
    } finally {
      setBusy("");
    }
  }

  const canDownloadQuestionnaire = Boolean(selectedProject?.artifacts?.questionnaire_final);
  const canDownloadStructure = Boolean(selectedProject?.artifacts?.structure_json);
  const canDownloadReport = Boolean(selectedProject?.artifacts?.fairset_report);

  return (
    <main>
      <header className="topbar">
        <h1>Logic</h1>
        <button type="button" className="secondary compact" onClick={() => void loadProjects()}>
          Refresh
        </button>
      </header>

      {error && <div className="error">{error}</div>}

      <section className="layout">
        <aside className="sidebar">
          <section className="panel">
            <div className="panelHeader">
              <h2>Projects</h2>
              <button className="textButton" onClick={() => setWorkspaceMode("new")}>
                New
              </button>
            </div>
            <div className="projectList">
              {projects.length === 0 ? (
                <p className="muted">No projects yet.</p>
              ) : (
                projects.map((project) => (
                  <button
                    type="button"
                    key={project.run_id}
                    className={project.run_id === selectedProject?.run_id ? "activeProject" : ""}
                    onClick={() => {
                      setWorkspaceMode("project");
                      void openProject(project.run_id);
                    }}
                  >
                    <strong>{projectName(project)}</strong>
                    <span>{projectListHint(project)}</span>
                  </button>
                ))
              )}
            </div>
          </section>
        </aside>

        <section className="workspace">
          {workspaceMode === "new" ? (
            <section className="menuBlock">
              <p className="workspaceLead">PDF questionnaire and data required. Fairset optional.</p>
              <label className="titleField">
                <span>Name</span>
                <input
                  type="text"
                  value={projectNameInput}
                  placeholder="Untitled"
                  onChange={(event) => setProjectNameInput(event.target.value)}
                />
              </label>
              <div className="workflowFields">
                <FileInput label="Questionnaire (PDF)" accept=".pdf" onChange={setQnrFile} />
                <FileInput
                  label="Data"
                  accept=".sav,.csv,.xlsx,.xls"
                  hint="Sav · CSV · Excel"
                  onChange={(file) => {
                    setDataFile(file);
                    if (file) {
                      setProjectNameInput(fileStem(file.name));
                    }
                  }}
                />
                <FileInput
                  label="Fairset"
                  accept=".sav,.csv,.xlsx,.xls"
                  hint="Optional · review in the same run"
                  onChange={setNewFairsetOptional}
                />
              </div>
              <button
                type="button"
                className="primary"
                disabled={Boolean(busy) || !qnrFile || !dataFile}
                onClick={() => void createProject()}
              >
                {busy === "Starting…" ? "…" : "Start"}
              </button>
              <details className="minorDetails">
                <summary>Questionnaire JSON only</summary>
                <FileInput
                  label="JSON"
                  accept=".json"
                  onChange={(file) => {
                    setQuestionnaireJsonFile(file);
                    if (file) {
                      setProjectNameInput(fileStem(file.name));
                    }
                  }}
                />
                <button
                  type="button"
                  className="secondary"
                  disabled={Boolean(busy)}
                  onClick={() => void createStructureProject()}
                >
                  {busy === "Generating structure from questionnaire" ? "…" : "Structure only"}
                </button>
              </details>
              <ProgressStatus busy={busy} progress={progress} />
            </section>
          ) : (
            <section className="menuBlock">
              {!selectedProject ? (
              <div className="emptyState">
                <strong>Select a project</strong>
              </div>
              ) : (
                <>
                  <div className="projectHeader">
                    <div>
                      <div className="renameRow">
                        <input
                          type="text"
                          value={renameInput}
                          onChange={(event) => setRenameInput(event.target.value)}
                        />
                        <button
                          className="secondary compact"
                          disabled={Boolean(busy) || renameInput.trim() === projectName(selectedProject)}
                          onClick={() => void renameProject()}
                        >
                          {busy === "Saving project name" ? "Saving..." : "Save"}
                        </button>
                      </div>
                    </div>
                  </div>

                  <ProgressStatus busy={busy} progress={progress} />

                  <div className="outputStrip inlineLabel">
                    <span>Files</span>
                    {canDownloadQuestionnaire && selectedProject ? (
                      <button
                        type="button"
                        className="secondary compact"
                        disabled={Boolean(busy)}
                        onClick={() => void downloadRunArtifact(selectedProject, "questionnaire_final")}
                      >
                        questionnaire.json
                      </button>
                    ) : null}
                    {canDownloadStructure && selectedProject ? (
                      <button
                        type="button"
                        className="secondary compact"
                        disabled={Boolean(busy)}
                        onClick={() => void downloadRunArtifact(selectedProject, "structure_json")}
                      >
                        structure.json
                      </button>
                    ) : selectedProject?.artifacts?.logics_json ? (
                      <button
                        type="button"
                        className="secondary compact"
                        disabled={Boolean(busy)}
                        onClick={() => void generateStructure()}
                      >
                        {busy === "Generating structure.json" ? "…" : "structure.json"}
                      </button>
                    ) : null}
                    {canDownloadReport && selectedProject ? (
                      <button
                        type="button"
                        className="secondary compact"
                        disabled={Boolean(busy)}
                        onClick={() => void downloadRunArtifact(selectedProject, "fairset_report")}
                      >
                        report
                      </button>
                    ) : null}
                  </div>

                  {!canDownloadReport ? (
                    <div className="splitSection">
                      <FileInput
                        label="Fairset"
                        accept=".sav,.csv,.xlsx,.xls"
                        hint="Add anytime · same project"
                        onChange={setFairsetForReview}
                      />
                      <button
                        type="button"
                        className="primary"
                        disabled={Boolean(busy) || !fairsetForReview || !selectedProject?.artifacts?.logics_json}
                        onClick={() => void reviewFairset()}
                      >
                        {busy === "Fairset review" ? "…" : "Run Fairset review"}
                      </button>
                    </div>
                  ) : null}

                  {selectedProject.missing_columns?.length ? (
                    <div className="warning">Missing columns: {selectedProject.missing_columns.join(", ")}</div>
                  ) : null}
                </>
              )}
            </section>
          )}
        </section>
      </section>
    </main>
  );
}

const mount = document.getElementById("root");
if (!mount) {
  throw new Error("#root element missing (check apps/web/index.html)");
}
createRoot(mount).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
