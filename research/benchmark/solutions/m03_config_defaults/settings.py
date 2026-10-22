from defaults import DEFAULTS


def load(text):
    config = {}
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            key, _, value = line.partition("=")
            config[key.strip()] = value.strip()
    return config


def get_setting(config, key):
    if key in config:
        return config[key]
    return DEFAULTS[key]
