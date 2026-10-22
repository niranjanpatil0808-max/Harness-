import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class TestDeploymentFiles(unittest.TestCase):
    def read(self, name):
        return (ROOT / name).read_text()

    def test_health_check_paths_match_the_server_route(self):
        self.assertIn("/healthz", self.read("Dockerfile"))
        self.assertIn("healthCheckPath: /healthz", self.read("render.yaml"))
        self.assertIn('"/healthz"', self.read("src/kintsugi/workspace/server.py"))

    def test_the_image_listens_on_the_network_but_needs_a_token(self):
        docker = self.read("Dockerfile")
        self.assertIn("KINTSUGI_HOST=0.0.0.0", docker)
        self.assertIn("util-linux", docker)  # unshare/mount for the sandbox
        self.assertNotRegex(docker, r"(?m)^(ENV\b.*\n?(\s+.*\n)*?)?\s*KINTSUGI_TOKEN=[A-Za-z0-9]")  # never bake a token into the image
        render = self.read("render.yaml")
        self.assertIn("key: KINTSUGI_TOKEN", render)
        self.assertIn("generateValue: true", render)
        self.assertRegex(render, r"key: KINTSUGI_API_KEY\s+sync: false")  # the key is never in the repository

    def test_no_secrets_are_committed_in_deployment_files(self):
        for name in ("Dockerfile", "render.yaml", ".devcontainer/devcontainer.json", "examples/smoke.config", "examples/study.config"):
            self.assertNotRegex(self.read(name), r"(sk-|gsk_|ghp_)[A-Za-z0-9]{10,}", name)

    def test_every_test_that_security_md_cites_exists(self):
        cited = set(re.findall(r"`(test_[a-z_]+\.py)`", self.read("SECURITY.md")))
        self.assertTrue(cited)
        for name in cited:
            self.assertTrue((ROOT / "tests" / name).is_file(), name)

    def test_documented_settings_exist_in_the_code(self):
        code = "".join(p.read_text() for p in (ROOT / "src" / "kintsugi").rglob("*.py"))
        for variable in re.findall(r"\| `(KINTSUGI_[A-Z_]+)`", self.read("docs/HOSTING.md")):
            self.assertIn(variable, code, variable)

    def test_the_model_study_workflow_spends_nothing_until_models_are_listed(self):
        config = self.read("examples/study.config")
        self.assertRegex(config, r"(?m)^STUDY_MODELS=\s*$")  # a push of this file must not burn quota
        self.assertIn("STUDY_MAX_CALLS", config)
        workflow = self.read(".github/workflows/workspace_study.yml")
        self.assertIn("examples/study.config", workflow)
        self.assertNotIn("sk-", workflow)

    def test_the_package_ships_its_web_files_and_licenses(self):
        pyproject = self.read("pyproject.toml")
        for pattern in ("web/*.html", "web/*.js", "web/*.css", "web/vendor/*"):
            self.assertIn(pattern, pyproject)


if __name__ == "__main__":
    unittest.main()
