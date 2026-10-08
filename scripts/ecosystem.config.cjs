/** PM2: collector, signal_engine (вместе с тестом стратегии), ws_server. */
const path = require("path");

const root = path.resolve(__dirname, "..");
const python = path.join(root, ".venv", "bin", "python");

function app(name, module, logFile) {
  return {
    name,
    cwd: root,
    script: python,
    args: `-m ${module}`,
    interpreter: "none",
    autorestart: true,
    max_restarts: 20,
    min_uptime: "10s",
    restart_delay: 3000,
    merge_logs: true,
    out_file: path.join(root, logFile),
    error_file: path.join(root, logFile),
    env: {
      PYTHONUNBUFFERED: "1",
    },
  };
}

module.exports = {
  apps: [
    app("collector", "collector", "logs-collector.txt"),
    app("signal-engine", "signal_engine", "logs-engine.txt"),
    app("ws-server", "ws_server", "logs-ws.txt"),
  ],
};
