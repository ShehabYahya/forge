# Detailed installation

See the repository-level [installation guide](../INSTALL.md). The wheel includes the Python package, optional skills, OpenCode adapter sources, the fallback command asset, and the built `dist/index.js` plugin entry. Registering that plugin also registers `/review-memory` through OpenCode configuration. The verified development sequence is TypeScript type checking, the plugin test suite, plugin bundling, then rebuilding the Python wheel.
