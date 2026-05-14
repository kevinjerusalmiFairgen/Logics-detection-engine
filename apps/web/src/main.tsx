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
  questionnaire_final: "07_questionnaire_final.json",
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
  onChange,
}: {
  label: string;
  accept: string;
  onChange: (file: File | null) => void;
}) {
  const [filename, setFilename] = useState("");

  return (
    <label className="field">
      <span>{label}</span>
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
  const [fairsetFile, setFairsetFile] = useState<File | null>(null);
  const [projectNameInput, setProjectNameInput] = useState("");
  const [renameInput, setRenameInput] = useState("");
  const [workspaceMode, setWorkspaceMode] = useState<"new" | "project">("new");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const pollTimer = useRef<number | null>(null);

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
    if (a.structure_json) return "structure";
    if (a.logics_json) return "logics";
    if (Object.keys(a).length > 0) return "artifacts";
    return "in progress…";
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
        await openProject(runId);
        await loadProjects();
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
    setBusy("Creating project");
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
    if (!fairsetFile) {
      setError("Upload a Fairset file first.");
      return;
    }
    setBusy("Checking Fairset");
    setProgress(null);
    setError("");
    const formData = new FormData();
    formData.append("fairset_file", fairsetFile);
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
        <div>
          <h1>Logic projects</h1>
        </div>
        <button className="secondary compact" onClick={() => void loadProjects()}>
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
                New project
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
                    <span>
                      {projectListHint(project)}
                      {(project.artifacts ?? {}).fairset_report ? " · reviewed" : ""}
                    </span>
                  </button>
                ))
              )}
            </div>
          </section>
        </aside>

        <section className="workspace">
          {workspaceMode === "new" ? (
            <section className="menuBlock">
              <label className="titleField">
                <span>Project name</span>
                <input
                  type="text"
                  value={projectNameInput}
                  placeholder="Untitled project"
                  onChange={(event) => setProjectNameInput(event.target.value)}
                />
              </label>
              <div className="uploadGrid">
              <FileInput label="Questionnaire PDF" accept=".pdf" onChange={setQnrFile} />
              <FileInput
                label="Data (.sav, .csv, .xlsx)"
                accept=".sav,.csv,.xlsx,.xls"
                onChange={(file) => {
                  setDataFile(file);
                  if (file) {
                    setProjectNameInput(fileStem(file.name));
                  }
                }}
              />
              </div>
              <button className="primary" disabled={Boolean(busy)} onClick={() => void createProject()}>
                {busy === "Creating project" ? "Running..." : "Generate"}
              </button>
              <div className="optionDivider">or</div>
              <div className="singleUpload">
                <FileInput
                  label="Questionnaire JSON"
                  accept=".json"
                  onChange={(file) => {
                    setQuestionnaireJsonFile(file);
                    if (file) {
                      setProjectNameInput(fileStem(file.name));
                    }
                  }}
                />
                <button className="secondary" disabled={Boolean(busy)} onClick={() => void createStructureProject()}>
                  {busy === "Generating structure from questionnaire" ? "Generating..." : "Generate structure only"}
                </button>
              </div>
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

                  <div className="actionsGrid">
                    {canDownloadQuestionnaire && selectedProject && (
                      <button
                        type="button"
                        className="secondary"
                        disabled={Boolean(busy)}
                        onClick={() => void downloadRunArtifact(selectedProject, "questionnaire_final")}
                      >
                        Questionnaire JSON
                      </button>
                    )}
                    {canDownloadStructure && selectedProject ? (
                      <button
                        type="button"
                        className="secondary"
                        disabled={Boolean(busy)}
                        onClick={() => void downloadRunArtifact(selectedProject, "structure_json")}
                      >
                        structure.json
                      </button>
                    ) : (
                      <button className="secondary" disabled={Boolean(busy)} onClick={() => void generateStructure()}>
                        {busy === "Generating structure.json" ? "Generating..." : "Generate structure"}
                      </button>
                    )}
                    {canDownloadReport && selectedProject && (
                      <button
                        type="button"
                        className="secondary"
                        disabled={Boolean(busy)}
                        onClick={() => void downloadRunArtifact(selectedProject, "fairset_report")}
                      >
                        Fairset report
                      </button>
                    )}
                  </div>

                  <section className="reviewPanel">
                    <h3>Fairset review</h3>
                    <FileInput label="Fairset (.sav, .csv, .xlsx)" accept=".sav,.csv,.xlsx,.xls" onChange={setFairsetFile} />
                    <button className="primary" disabled={Boolean(busy)} onClick={() => void reviewFairset()}>
                      {busy === "Checking Fairset" ? "Checking..." : "Check"}
                    </button>
                  </section>

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
