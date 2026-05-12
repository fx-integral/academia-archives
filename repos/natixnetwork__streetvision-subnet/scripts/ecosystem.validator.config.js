module.exports = {
  apps: [
    {
      name: "natix_validator",
      script: "scripts/start_validator.sh",
      interpreter: "bash",
    },
    {
      name: "natix_cache_updater",
      script: "scripts/start_cache_updater.sh",
      interpreter: "bash",
    },
    {
      name: "natix_synthetic_generator",
      script: "scripts/start_synthetic_generator.sh",
      interpreter: "bash",
    }
  ]
}
