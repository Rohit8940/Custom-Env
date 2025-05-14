import React, { useState, useCallback } from "react";
import axios from "axios";
import "./styles.css";
const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

function App() {
  const [packages, setPackages] = useState([]);
  const [input, setInput] = useState("");
  const [treeData, setTreeData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [expandedNodes, setExpandedNodes] = useState(new Set());
  const [actionMode, setActionMode] = useState("view"); // 'view' or 'download'
  const [envConfig, setEnvConfig] = useState({
    pythonVersion: "3.9",
    envName: "offline_env"
  });
  const [downloadStatus, setDownloadStatus] = useState(null);

  const handleAdd = useCallback(() => {
    if (input.trim()) {
      setPackages(prev => [...prev, input.trim()]);
      setInput("");
      setError(null);
    }
  }, [input]);

  const handleRemove = useCallback((pkgToRemove) => {
    setPackages(prev => prev.filter(p => p !== pkgToRemove));
    setTreeData(null);
  }, []);

  const toggleNode = useCallback((nodeId) => {
    setExpandedNodes(prev => {
      const newExpanded = new Set(prev);
      newExpanded.has(nodeId) ? newExpanded.delete(nodeId) : newExpanded.add(nodeId);
      return newExpanded;
    });
  }, []);

  const handleFetchTree = async () => {
    if (packages.length === 0) return;
    
    setLoading(true);
    setError(null);
    setTreeData(null);
    setDownloadStatus(null);

    try {
      const res = await axios.post(`${API_URL}/get-wheels`, {
        packages,
      });
      
      if (res.data?.wheels) {
        setTreeData(res.data.wheels);
        const defaultExpanded = new Set();
        res.data.wheels.forEach(pkg => defaultExpanded.add(`${pkg.name}-${pkg.version}`));
        setExpandedNodes(defaultExpanded);
      } else {
        setError("No data received from server");
      }
    } catch (err) {
      console.error("Error fetching wheel URLs:", err);
      setError(err.response?.data?.message || err.message || "Failed to fetch dependencies");
    } finally {
      setLoading(false);
    }
  };

  const handleCreateEnvironment = async () => {
    if (packages.length === 0) return;
    
    setLoading(true);
    setError(null);
    setTreeData(null);
    setDownloadStatus("Preparing environment...");

    try {
      const res = await axios.post(`${API_URL}/create-offline-environment`, {
        packages,
        python_version: envConfig.pythonVersion,
        env_name: envConfig.envName
      });
      
      if (res.data?.status === "success") {
        setDownloadStatus(`Environment created successfully! Archive path: ${res.data.archive_path}`);
        // Also show the tree of what was installed
        const treeRes = await axios.post(`${API_URL}/get-wheels`, {
          packages,
        });
        setTreeData(treeRes.data?.wheels || []);
      } else {
        setError("Failed to create environment");
      }
    } catch (err) {
      console.error("Error creating environment:", err);
      setError(err.response?.data?.message || err.message || "Failed to create environment");
    } finally {
      setLoading(false);
    }
  };

  const renderTree = (nodes, depth = 0) => {
    if (!nodes || nodes.length === 0) return null;

    return (
      <ul className={`tree-list ${depth > 0 ? "nested" : ""}`}>
        {nodes.map((node) => {
          const nodeId = `${node.name}-${node.version}`;
          const isExpanded = expandedNodes.has(nodeId);
          const hasChildren = node.dependencies && node.dependencies.length > 0;

          return (
            <li key={nodeId} className="tree-node">
              <div
                className="node-content"
                style={{ paddingLeft: `${depth * 16 + 8}px` }}
              >
                {hasChildren ? (
                  <button
                    className="toggle-button"
                    onClick={() => toggleNode(nodeId)}
                    aria-label={isExpanded ? "Collapse" : "Expand"}
                  >
                    {isExpanded ? "▼" : "▶"}
                  </button>
                ) : (
                  <span className="leaf-spacer">•</span>
                )}
                <span className="package-name">
                  <strong>{node.name}</strong> <span className="version">{node.version}</span>
                </span>
                {node.url && (
                  <a
                    href={node.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="wheel-link"
                    onClick={(e) => e.stopPropagation()}
                    download
                  >
                    Download Wheel
                  </a>
                )}
                {node.file && (
                  <span className="file-info">
                    Saved as: {node.file}
                  </span>
                )}
              </div>
              {isExpanded && hasChildren && renderTree(node.dependencies, depth + 1)}
            </li>
          );
        })}
      </ul>
    );
  };

  return (
    <div className="app-container">
      <div className="centered-content">
        <header className="app-header">
          <h1>🌳 Python Package Dependency Tree</h1>
          <p>Visualize dependencies or create portable offline environments</p>
        </header>

        <div className="input-section">
          <div className="input-group">
            <input
              type="text"
              placeholder="e.g., flask or numpy==1.24.0"
              className="input-field"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleAdd()}
              aria-label="Package name and version"
            />
            <button 
              onClick={handleAdd} 
              className="add-button"
              disabled={!input.trim()}
            >
              Add Package
            </button>
          </div>

          {packages.length > 0 && (
            <div className="package-tags">
              {packages.map((pkg, i) => (
                <div key={`${pkg}-${i}`} className="package-tag">
                  <span>{pkg}</span>
                  <button
                    onClick={() => handleRemove(pkg)}
                    className="remove-tag"
                    aria-label={`Remove ${pkg}`}
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="mode-selection">
          <div className="mode-options">
            <button
              className={`mode-button ${actionMode === 'view' ? 'active' : ''}`}
              onClick={() => setActionMode('view')}
            >
              View Dependency Tree
            </button>
            <button
              className={`mode-button ${actionMode === 'download' ? 'active' : ''}`}
              onClick={() => setActionMode('download')}
            >
              Create Portable Environment
            </button>
          </div>
        </div>

        {actionMode === 'download' && (
          <div className="env-config">
            <h3>Environment Configuration</h3>
            <div className="config-fields">
              <div className="config-field">
                <label>Python Version:</label>
                <input
                  type="text"
                  value={envConfig.pythonVersion}
                  onChange={(e) => setEnvConfig({...envConfig, pythonVersion: e.target.value})}
                />
              </div>
              <div className="config-field">
                <label>Environment Name:</label>
                <input
                  type="text"
                  value={envConfig.envName}
                  onChange={(e) => setEnvConfig({...envConfig, envName: e.target.value})}
                />
              </div>
            </div>
          </div>
        )}

        <div className="action-section">
          {actionMode === 'view' ? (
            <button
              onClick={handleFetchTree}
              disabled={loading || packages.length === 0}
              className="action-button"
            >
              {loading ? (
                <>
                  <span className="spinner"></span> Building Tree...
                </>
              ) : (
                "View Dependency Tree"
              )}
            </button>
          ) : (
            <button
              onClick={handleCreateEnvironment}
              disabled={loading || packages.length === 0}
              className="action-button download-button"
            >
              {loading ? (
                <>
                  <span className="spinner"></span> Creating Environment...
                </>
              ) : (
                "Create Portable Environment"
              )}
            </button>
          )}
        </div>

        {error && (
          <div className="error-message">
            ⚠️ {error}
          </div>
        )}

        {downloadStatus && (
          <div className="download-status">
            {downloadStatus}
          </div>
        )}

        <div className="tree-container">
          {treeData ? (
            renderTree(treeData)
          ) : (
            <div className="empty-state">
              {loading ? (
                <div className="loading-message">
                  <div className="spinner"></div>
                  {actionMode === 'view' ? "Loading dependencies..." : "Creating environment..."}
                </div>
              ) : (
                <div className="instruction">
                  {packages.length > 0 ? (
                    actionMode === 'view' ? 
                      "Click 'View Dependency Tree' to visualize package dependencies" :
                      "Click 'Create Portable Environment' to build offline environment"
                  ) : (
                    "Add packages above to get started"
                  )}
                </div>
              )}
            </div>
          )}
        </div>

        {treeData && actionMode === 'download' && (
          <div className="download-notes">
            <p>
              <strong>Note:</strong> The environment has been packaged with all dependencies.
              You can transfer the archive to any offline computer and use it by activating the environment.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

export default App;