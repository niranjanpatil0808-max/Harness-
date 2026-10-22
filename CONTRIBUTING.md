# Contributing

Thanks for helping. Kintsugi is a small, dependency-free Python app with a vanilla-JS interface, so it is easy to run and change.

## Run it and test it

```bash
pip install -e ".[push]"                      # "push" adds the optional cryptography package (notifications, encrypted backup)
python -m unittest discover -s tests          # ~550 offline tests, about 3 minutes, no API key needed
kintsugi workspace serve                      # run the app
```

Browser tests (need Node + Playwright, run against a scripted model): `bash tests/ui/run_all.sh`, or a few at a time with
`SUITES="team tasks" bash tests/ui/run_all.sh`. Details in [tests/ui/README.md](tests/ui/README.md).

## Ground rules

- **No runtime dependencies** besides the standard library (the optional `cryptography` aside). The two web libraries are vendored.
- **Safety first.** Anything that lets an agent or a person do more than before needs a test that shows who can and cannot do it. Role
  checks live in `team.py` (`required_role`, deny-by-default). New endpoints go in `server.py`; add them to the role tables.
- **Be honest in docs.** If something was only tested against a fake, say so. `docs/STATUS.md` is the running handoff note.
- **Match the surrounding code**: naming, comment density, plain language in user-facing text.
- Add a test with every fix. Security fixes get a regression test named after what it prevents.

## Reporting a security problem

Please do not open a public issue. Use GitHub's "Report a vulnerability" on the Security tab, or contact the maintainer privately.
See [SECURITY.md](SECURITY.md) for what is and is not protected.

## Pull requests

Describe what changed and why, what you ran, and anything you could not verify. Keep them focused.
