"""Run multiple reconcilers with one configuration, leader lease and shutdown path."""

from cloudcoil.application import Application
from examples.patterns.dependency_rollout import controller as reloader
from examples.patterns.workload_summary import controller as summary


def build_app() -> Application:
    return Application("workload-tools", reloader(), summary(), leader_election=True)


if __name__ == "__main__":
    build_app().main()
