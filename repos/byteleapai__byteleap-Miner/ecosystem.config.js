/**
 * PM2 Configuration for ByteLeap Miner
 *
 * Usage:
 *   Start:     pm2 start ecosystem.config.js
 *   Stop:      pm2 stop ecosystem.config.js
 *   Restart:   pm2 restart ecosystem.config.js
 *   Logs:      pm2 logs
 *   Monitor:   pm2 monit
 */

module.exports = {
  apps: [
    {
      name: 'byteleap-miner',
      script: 'scripts/run_miner.py',
      interpreter: 'python3',
      args: '--config config/miner_config.yaml',
      cwd: './',
      instances: 1,
      exec_mode: 'fork',
      autorestart: true,
      watch: false,
      max_memory_restart: '2G',
      error_file: 'logs/pm2-miner-error.log',
      out_file: 'logs/pm2-miner-out.log',
      log_file: 'logs/pm2-miner-combined.log',
      time: true,
      merge_logs: true,
      env: {
        PYTHONUNBUFFERED: '1',
        PYTHONPATH: '.',
      },
      // Restart strategy
      min_uptime: '10s',
      max_restarts: 10,
      restart_delay: 5000,
      // Kill timeout
      kill_timeout: 30000,
      // Listen timeout
      listen_timeout: 10000,
    },
  ],
};
