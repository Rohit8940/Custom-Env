import React, { useState } from "react";
import axios from "axios";
import "./styles.css";

function App() {
  const [packages, setPackages] = useState([]);
  const [input, setInput] = useState("");
  const [treeData, setTreeData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [expandedNodes, setExpandedNodes] = useState(new Set());
  const API_URL = import.meta.env.VITE_API_URL

  const handleAdd = () => {
    if (input.trim()) {
      setPackages([...packages, input.trim()]);
      setInput("");
    }
  };

  const handleRemove = (pkg) => {
    setPackages(packages.filter((p) => p !== pkg));
  };

  const toggleNode = (nodeId) => {
    const newExpanded = new Set(expandedNodes);
    if (newExpanded.has(nodeId)) {
      newExpanded.delete(nodeId);
    } else {
      newExpanded.add(nodeId);
    }
    setExpandedNodes(newExpanded);
  };

  const handleFetch = async () => {
    if (packages.length === 0) return;
    setLoading(true);
    try {
      const res = await axios.post(`${API_URL}/get-wheels`, {
        packages,
      });
      setTreeData(res.data);
      // Expand root nodes by default
      const defaultExpanded = new Set();
      res.data.forEach((pkg) => defaultExpanded.add(pkg.name + pkg.version));
      setExpandedNodes(defaultExpanded);
    } catch (err) {
      console.error("Error fetching wheel URLs:", err);
    } finally {
      setLoading(false);
    }
  };

  const renderTree = (nodes, depth = 0) => {
    if (!nodes) return null;

    return (
      <ul className={`tree-list ${depth > 0 ? "nested" : ""}`}>
        {nodes.map((node) => {
          const nodeId = node.name + node.version;
          const isExpanded = expandedNodes.has(nodeId);
          const hasChildren = node.dependencies && node.dependencies.length > 0;

          return (
            <li key={nodeId} className="tree-node">
              <div
                className="node-content"
                style={{ paddingLeft: `${depth * 16 + 8}px` }}
              >
                {hasChildren && (
                  <span
                    className="toggle"
                    onClick={() => toggleNode(nodeId)}
                  >
                    {isExpanded ? "▼" : "▶"}
                  </span>
                )}
                {!hasChildren && <span className="leaf-spacer">•</span>}
                <span className="package-name">
                  {node.name} {node.version}
                </span>
                {node.url && (
                  <a
                    href={node.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="wheel-link"
                    onClick={(e) => e.stopPropagation()}
                  >
                    Download Wheel
                  </a>
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
          <p>Visualize and download package wheels</p>
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
            />
            <button onClick={handleAdd} className="add-button">
              Add Package
            </button>
          </div>

          {packages.length > 0 && (
            <div className="package-tags">
              {packages.map((pkg, i) => (
                <div key={i} className="package-tag">
                  <span>{pkg}</span>
                  <button
                    onClick={() => handleRemove(pkg)}
                    className="remove-tag"
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="action-section">
          <button
            onClick={handleFetch}
            disabled={loading || packages.length === 0}
            className="fetch-button"
          >
            {loading ? (
              <>
                <span className="spinner"></span> Building Tree...
              </>
            ) : (
              "Build Dependency Tree"
            )}
          </button>
        </div>

        <div className="tree-container">
          {treeData ? (
            renderTree(treeData)
          ) : (
            <div className="empty-state">
              {loading ? (
                <div className="loading-message">Loading dependencies...</div>
              ) : (
                <div className="instruction">
                  Add packages above and click "Build Dependency Tree"
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default App;