# Detailed installation

See the repository-level [installation guide](../INSTALL.md). The wheel includes the Python package, optional Anvil skill, OpenCode adapter sources, and the built `dist/index.js` plugin entry. The verified development sequence is TypeScript type checking, the plugin test suite, plugin bundling, then rebuilding the Python wheel so it packages the current bundle.
