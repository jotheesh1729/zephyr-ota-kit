# Contributing

This is a small demonstration project with one maintainer and one test board. Help is welcome, within what can be checked.

## Reporting a problem

Open an issue. It helps a lot if it contains:

- The board, the Zephyr and MCUboot revisions, and the command line you used.
- The report of `scripts/ota_doctor.py <build directory>`, or its `--json` output.
- The console log from the MCUboot banner to the failure. `scripts/ota_update.py` prints it.
- What you expected and what happened.

Remove anything private first: paths with your user name, network names, device addresses.
For a security problem do not open a public issue, see [SECURITY.md](SECURITY.md).

## Sending a change

1. Keep it small and about one thing.
2. Run what can run without hardware, and say that you did:

   ```sh
   python3 -m unittest discover -s tests/doctor -v
   python3 tests/check_paths.py
   scripts/static_analysis.py <an image build directory> --accepted tests/static/accepted.txt
   ```

3. If the change touches the firmware, the kit, or the update scripts, it has to be tested on a board. Say which board, which tests from `tests/run_tests.py`, and paste the result table. If you could not test on hardware, say so plainly. The maintainer may not be able to test it either: only `disco_l475_iot1` is available.
4. New source files need the copyright and SPDX lines the other files have.

## Rules this project holds itself to

They apply to contributions as well.

- **No invented numbers.** Every measurement in the documentation comes from a run. If something was not measured or not tested, the text says "not tested".
- **A test is not changed to make it pass.** If the device behaves differently than expected, that is the finding. See case 4 in `docs/RESULTS.md` for an example.
- **Claims have a source.** A statement about Zephyr or MCUboot points to the file or document it comes from. A rule in the doctor comes from a real problem or from the documentation, and `docs/DOCTOR.md` says which.
- **No keys, no tokens, no home directory paths** in the repository. `tests/check_paths.py` checks the last one.
- Plain writing: short sentences, no filler.

## A new board

Start with [docs/PORTING.md](docs/PORTING.md). A board counts as supported here only after the failure suite ran on it.
A compile only port is welcome too, and is listed as such in the table of supported boards in the README.

## A new doctor rule

It needs an ID, a status, evidence, a fix hint, a fixture captured from a real build with `tests/doctor/capture.py`, and a line in `docs/DOCTOR.md` saying where the rule comes from.

## License

By contributing you agree that your contribution is licensed under the Apache License 2.0 of this project, see [LICENSE](LICENSE).
