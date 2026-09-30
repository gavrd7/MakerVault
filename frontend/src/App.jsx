import React, { useCallback, useEffect, useState } from "react";
import { AllCommunityModule, ModuleRegistry } from "ag-grid-community";
import { apiFetch } from "./api";
import BoardsPage, { ImportBoardModal } from "./components/BoardsPage";
import ComponentsPage from "./components/ComponentsPage";
import Dashboard from "./components/Dashboard";
import InventoryPage from "./components/InventoryPage";
import ProjectsPage from "./components/ProjectsPage";
import FilesPage from "./components/FilesPage";
import AboutPage from "./components/AboutPage";
import SettingsPage from "./components/SettingsPage";
import PrintingPage from "./components/PrintingPage";
import GlobalSearch from "./components/GlobalSearch";
import SearchPage from "./components/SearchPage";
import MakerTagsPage from "./components/MakerTagsPage";
import WiringPage from "./components/WiringPage";

ModuleRegistry.registerModules([AllCommunityModule]);

const NAV = ["Dashboard", "Search", "Board Catalogue", "Components", "Projects", "Inventory", "3D Printing", "Files", "Interactive Wiring", "Maker Tags", "Settings", "About"];

export default function App() {
  const [section, setSection] = useState("Dashboard");
  const [dashboard, setDashboard] = useState(null);
  const [inventory, setInventory] = useState([]);
  const [boards, setBoards] = useState([]);
  const [components, setComponents] = useState([]);
  const [projects, setProjects] = useState([]);
  const [config, setConfig] = useState(null);
  const [error, setError] = useState("");
  const [importOpen, setImportOpen] = useState(false);
  const [notice, setNotice] = useState("");
  const [projectTarget, setProjectTarget] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [searchTarget, setSearchTarget] = useState(null);
  const [tagResolveToken, setTagResolveToken] = useState("");

  const refreshDashboard = useCallback(async () => {
    const result = await apiFetch("/api/dashboard/");
    setDashboard(result);
  }, []);

  const refreshInventory = useCallback(async () => {
    const result = await apiFetch("/api/inventory/");
    setInventory(result.rows || []);
  }, []);

  useEffect(() => {
    if (section !== "Projects") return;
    apiFetch("/api/projects/")
      .then(result => setProjects(result.rows || []))
      .catch(err => setError(err.message || "MakerVault could not refresh projects."));
  }, [section]);

  useEffect(() => {
    Promise.all([
      apiFetch("/api/dashboard/"), apiFetch("/api/inventory/"), apiFetch("/api/config/"),
      apiFetch("/api/boards/"), apiFetch("/api/components/"), apiFetch("/api/projects/"),
    ]).then(([d, i, c, b, comp, p]) => {
      setDashboard(d); setInventory(i.rows || []); setConfig(c); setBoards(b.rows || []); setComponents(comp.rows || []); setProjects(p.rows || []);
    }).catch(err => setError(err.message || "MakerVault could not load its initial data."));
  }, []);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const incomingTag = params.get("tag");
    if (incomingTag) {
      setTagResolveToken(incomingTag);
      setSection("Maker Tags");
    }
  }, []);

  function openSearchResult(result) {
    if (!result) return;
    setSearchTarget({ ...result, token: Date.now() });
    if (result.type === "projects") {
      setProjectTarget(result.id);
      setSection("Projects");
      return;
    }
    setSection(result.section || "Search");
  }

  function openAdvancedSearch(query = "") {
    setSearchQuery(query);
    setSection("Search");
  }

  function openTagTarget(tag) {
    if (!tag?.target?.id) return;
    const token = Date.now();
    if (tag.target_type === "project") {
      setProjectTarget(tag.target.id);
      setSection("Projects");
      return;
    }
    if (tag.target_type === "inventory") {
      setSearchTarget({ type: "inventory", id: tag.target.id, section: "Inventory", token });
      setSection("Inventory");
      return;
    }
    if (tag.target_type === "spool") {
      setSearchTarget({ type: "spools", id: tag.target.id, section: "3D Printing", token });
      setSection("3D Printing");
      return;
    }
    if (tag.target_type === "printer") {
      setSearchTarget({ type: "printers", id: tag.target.id, section: "3D Printing", token });
      setSection("3D Printing");
      return;
    }
    if (tag.target_type === "location") {
      setSection("3D Printing");
    }
  }

  function page() {
    if (section === "Dashboard") return <Dashboard dashboard={dashboard} inventory={inventory} onNavigate={setSection} />;
    if (section === "Search") return <SearchPage initialQuery={searchQuery} projects={projects} onOpenResult={openSearchResult} />;
    if (section === "Maker Tags") return <MakerTagsPage config={config} resolveToken={tagResolveToken} onResolveConsumed={() => { setTagResolveToken(""); const params = new URLSearchParams(window.location.search); params.delete("tag"); const query = params.toString(); window.history.replaceState({}, "", window.location.pathname + (query ? "?" + query : "") + window.location.hash); }} onChanged={refreshDashboard} onOpenTarget={openTagTarget} />;
    if (section === "Interactive Wiring") return <WiringPage boards={boards} components={components} inventory={inventory} projects={projects} config={config} onOpenProject={projectId => { setProjectTarget(projectId); setSection("Projects"); }} />;
    if (section === "Inventory") return <InventoryPage inventory={inventory} setInventory={setInventory} boards={boards} components={components} projects={projects} config={config} refreshDashboard={refreshDashboard} openItemId={searchTarget?.type === "inventory" ? searchTarget.id : ""} openToken={searchTarget?.token} />;
    if (section === "Board Catalogue") return <BoardsPage boards={boards} setBoards={setBoards} components={components} projects={projects} config={config} onOpenImport={() => setImportOpen(true)} refreshDashboard={refreshDashboard} openBoardId={searchTarget?.type === "boards" ? searchTarget.id : ""} openToken={searchTarget?.token} onInventoryCreated={async item => { setInventory(rows => [...rows.filter(row => row.id !== item.id), item].sort((a,b) => a.inventory_id.localeCompare(b.inventory_id))); await refreshDashboard(); }} />;
    if (section === "Components") return <ComponentsPage components={components} setComponents={setComponents} boards={boards} projects={projects} config={config} refreshDashboard={refreshDashboard} openComponentId={searchTarget?.type === "components" ? searchTarget.id : ""} openToken={searchTarget?.token} onInventoryCreated={async item => { setInventory(rows => [...rows.filter(row => row.id !== item.id), item].sort((a,b) => a.inventory_id.localeCompare(b.inventory_id))); await refreshDashboard(); }} />;
    if (section === "Projects") return <ProjectsPage projects={projects} setProjects={setProjects} config={config} refreshDashboard={refreshDashboard} refreshInventory={refreshInventory} boards={boards} components={components} inventory={inventory} openProjectId={projectTarget} onOpenConsumed={() => setProjectTarget("")} />;
    if (section === "3D Printing") return <PrintingPage config={config} projects={projects} searchTarget={searchTarget} />;
    if (section === "Files") return <FilesPage projects={projects} config={config} searchTarget={searchTarget?.type === "files" ? searchTarget : null} onOpenProject={projectId => { setProjectTarget(projectId); setSection("Projects"); }} />;
    if (section === "Settings") return <SettingsPage config={config} />;
    return <AboutPage config={config} />;
  }

  return <div className="shell">
    <aside>
      <div className="brand"><img className="brandLogo" src="/static/core/makervault-logo.jpg" alt="MakerVault" /><small className="brandVersion">{config?.version ? "v" + config.version : "version loading…"} · AGPL</small></div>
      <GlobalSearch onOpenResult={openSearchResult} onOpenAdvanced={openAdvancedSearch} />
      <nav>{NAV.filter(n => n !== "Settings" || config?.is_staff).map(n => <button key={n} className={section === n ? "active" : ""} onClick={() => setSection(n)}>{n}</button>)}</nav>
      <div className="asideBottom"><a href="/admin/">Administration</a><a href="/accounts/2fa/">Account &amp; Security</a><a href="/accounts/logout/">Sign out</a></div>
    </aside>
    <main>
      <header><div><h1>{section}</h1><p>{config ? `${config.user} · ${config.timezone} · ${config.currency}` : "Loading MakerVault…"}</p></div>{section === "Board Catalogue" && config?.permissions?.add_board && <button className="primary" onClick={() => setImportOpen(true)}>＋ Import URL</button>}</header>
      {error && <div className="error">{error}</div>}{notice && <div className="notice">{notice}<button onClick={() => setNotice("")}>×</button></div>}
      {page()}
    </main>
    {importOpen && <ImportBoardModal onClose={() => setImportOpen(false)} onImported={async (board, created) => {
      setBoards(rows => {
        const filtered = rows.filter(existing => existing.id !== board.id);
        return [...filtered, board].sort((a,b) => a.display_name.localeCompare(b.display_name));
      });
      setImportOpen(false); setNotice(created ? `${board.display_name} was added to the catalogue.` : `${board.display_name} already existed; missing source details were merged.`); await refreshDashboard();
    }} />}
  </div>;
}
