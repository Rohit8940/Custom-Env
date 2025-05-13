// src/components/DependencyTree.jsx
import React from 'react';
import Tree from 'react-animated-tree';

const DependencyTree = ({ node }) => {
  return (
    <Tree content={`${node.name}@${node.version}`} open>
      {node.dependencies &&
        node.dependencies.map((child, index) => (
          <DependencyTree key={index} node={child} />
        ))}
    </Tree>
  );
};

export default DependencyTree;
