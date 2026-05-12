module.exports = {
  apps: [{
    name: "djinn-validator",
    script: ".venv/bin/python",
    args: "-m djinn_validator.main",
    cwd: "/root/djinn/validator",
    // Give the graceful shutdown handler (15s) time to finish before SIGKILL.
    // Default is 1600ms which is far too short, leaving zombie workers.
    kill_timeout: 20000,
    // Wait for the port to become available before considering "started".
    wait_ready: false,
    // Kill the entire process tree (uvicorn workers, not just the main PID).
    treekill: true,
    // Don't restart more than 15 times in 15 minutes (crash-loop protection).
    max_restarts: 15,
    min_uptime: "10s",
  }],
};
