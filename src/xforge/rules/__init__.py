"""Design rules. Importing this package registers every rule module."""

from xforge.rules.base import Finding, Rule, Severity, registry, rule, run

__all__ = ["Finding", "Rule", "Severity", "registry", "rule", "run"]
