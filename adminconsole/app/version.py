"""Single source of truth for the application version.

Bump this on every release. The GitHub Actions workflow reads this file
to tag the Docker image (ghcr.io/rvssian-sez/adminconsole:<version> + :latest).
Displayed in the sidebar footer and Settings -> About.
"""

__version__ = "0.1.0-alpha.1"
