"""Example plugins you can preview and install from Settings > Plugins. They are ordinary manifests (see docs/PLUGINS.md).

The two that call web APIs have been checked for format only: the services themselves have not been called from this project's tests.
"""

EXAMPLES = {
    "writing-style": {
        "id": "writing-style", "name": "Writing style", "version": "1.0.0", "author": "Kintsugi examples",
        "description": "Skills only: short rules for clear writing. No internet, no secrets.",
        "skills": [{"name": "clear-writing", "description": "Plain, short, useful writing",
                    "text": "When you write for people:\n- Lead with the answer or the decision, then the reasons.\n- Use short sentences and everyday words.\n- Use a list when there are three or more parallel items.\n- Say what you do not know instead of guessing."}],
    },
    "open-meteo": {
        "id": "open-meteo", "name": "Weather (Open-Meteo)", "version": "1.0.0", "author": "Kintsugi examples",
        "description": "Current weather for a latitude and longitude from open-meteo.com. Needs no key.",
        "skills": [{"name": "weather-answers", "description": "How to answer weather questions",
                    "text": "For weather questions, find the coordinates of the place yourself, call open_meteo__now, then answer in one or two sentences with the temperature in Celsius and mention the source."}],
        "tools": [{"name": "now", "description": "Current weather at a latitude/longitude", "method": "GET",
                   "url": "https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true",
                   "hosts": ["api.open-meteo.com"],
                   "params": {"lat": {"type": "number", "description": "latitude, e.g. 18.52"}, "lon": {"type": "number", "description": "longitude, e.g. 73.85"}}}],
    },
    "github-issues": {
        "id": "github-issues", "name": "GitHub issues (read only)", "version": "1.0.0", "author": "Kintsugi examples",
        "description": "Lists recent issues of a repository. Needs a read-only GitHub token saved as the secret GITHUB_TOKEN on the agent.",
        "tools": [{"name": "list", "description": "Recent issues of a GitHub repository", "method": "GET",
                   "url": "https://api.github.com/repos/{owner}/{repo}/issues?state={state}&per_page=10",
                   "hosts": ["api.github.com"],
                   "params": {"owner": {"type": "string", "max_length": 60}, "repo": {"type": "string", "max_length": 100},
                              "state": {"type": "string", "enum": ["open", "closed", "all"], "required": False}},
                   "auth": {"secret": "GITHUB_TOKEN", "header": "Authorization", "prefix": "Bearer "}}],
    },
}
