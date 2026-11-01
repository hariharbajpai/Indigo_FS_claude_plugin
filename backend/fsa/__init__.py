"""Flight Safety Command backend (v0.11.0). Standard library only."""
VERSION = "0.11.0"
PLUGIN = "flight-safety-agents"
CHIEF_ID = "chief"
CHIEF_NAME = "Dhruv Rebbapragada"
CHIEF_ROLE = "Chief of Flight Safety"
CHECKER_ID = "checker"
CHECKER_NAME = "File Checker"
CHECKER_ROLE = "Documentation Controller"
HIRE_CAP = 5
SYSTEM_ID = "system"

# Which Claude each kind of agent runs on. "inherit" = whatever the Claude Code session itself uses.
MODEL_CHOICES = ("inherit", "haiku", "sonnet", "opus")
MODEL_ROLES = ("chief", "checker", "head", "hired")
