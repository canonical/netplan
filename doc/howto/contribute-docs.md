# How to contribute documentation
This guide provides all the information necessary to contribute to the Netplan documentation, especially if you're contributing for the first time.

## Reporting an issue

To report an issue in Netplan documentation, [file a bug](https://bugs.launchpad.net/netplan/+filebug?field.tags=documentation) about it in our bug tracker on Launchpad. Remember to add a `documentation` tag.
to it.

## Modifying documentation online

Each documentation page rendered on the web contains an **Edit this page** link in the top-right corner. Clicking this button leads you to the GitHub
web editor where you can propose changes to the corresponding page.

Remember to first check the [latest version](https://netplan.readthedocs.io/en/latest/)
of our documentation and make your proposal based on that revision.

## Contributing on GitHub

To follow a Git development workflow, `checkout` the
[Netplan repository](https://github.com/canonical/netplan) and contribute your
changes as [pull requests](https://github.com/canonical/netplan/pulls).

## Directory structure
All the documentation files are located in the `doc/` directory. The `doc/` directory contains sub-directories corresponding to different [Diátaxis](https://diataxis.fr/) sections:
* `tutorial`
* `explanation`
* `howto`
* `reference`

Add new articles in the appropriate directory. You can read about [how Ubuntu implements Diátaxis for documentation](https://ubuntu.com/blog/diataxis-a-new-foundation-for-canonical-documentation).

## Building the documentation
Follow these steps to build the documentation on your local machine.
1. Fork the [Netplan repository](https://github.com/canonical/netplan). Visit [Fork a repository](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/working-with-forks/fork-a-repo) for instructions.

2. Clone the repository to your machine:
    ```
    git clone git@github.com:your_user_name/netplan.git
    ```
3. Navigate to the `doc/` directory within the cloned repository:
    ```
    cd netplan/doc
    ```

4. Install `make` on your machine if you don't have it:
    ```
    sudo apt-get install make
    ```
    :::{note}
    The `make` command is compatible with Unix systems. If you're on Windows, you can [install Ubuntu with WSL to follow along](https://github.com/canonical/open-documentation-academy/blob/main/getting-started/start_with_WSL.md).
    :::

5. Within the `doc/` directory, run the `make` command to build and serve the documentation:
    ```
    make run
    ```
    After you run the command, visit `http://127.0.0.1:8000` in your browser to view the local copy of the documentation.

    You can find all the HTML files in the `.build/` directory.

    We use the Sphinx `autobuild` module, so that any edits you make (and save) as you work are applied, and the documentation refreshes immediately.

## Documentation format
The Netplan documentation is built with Sphinx using the reStructuredText and Markdown mark-up languages. If you're new to reStructuredText, read our [reStructuredText style guide](https://canonical-documentation-with-sphinx-and-readthedocscom.readthedocs-hosted.com/style-guide/).

## Testing the documentation
Test the documentation before submitting a pull request. Run the following commands from within the `doc/` directory to test the documentation locally:

|command  |use|
|---------|-----|
| `make spelling` | Check for spelling errors. This command checks the HTML files in the `_build` directory. Fix any errors in the corresponding Markdown file.|
| `make linkcheck`| Check for broken links|
| `make woke` | Check for non-inclusive language |

:::{note}
For the `make spelling` command to work, you must have `aspell` installed. You can install it with `sudo apt-get install aspell`.
:::