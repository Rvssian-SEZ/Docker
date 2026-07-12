"""Single source of truth for the application version.

Bump this on every release. The GitHub Actions workflow reads this file
to tag the Docker image (ghcr.io/rvssian-sez/itops2:<version> + :latest).
Displayed in the sidebar footer and Settings -> About.
"""

__version__ = "2.0.0-alpha.1"
