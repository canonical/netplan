# How to contribute documentation
This guide aims to help you with all the information necessary to contribute to the Netplan documentation, especially if you're contributing for the first time.

## Reporting an issue

If you find any issue in Netplan documentation please [file a bug report](https://bugs.launchpad.net/netplan/+filebug?field.tags=documentation) about it in our bug tracker on Launchpad. Remember to add a `documentation`` tag
to it.

## Modifying documentation online

Each documentation page rendered on the web contains an **Edit this **page** link at the top-right of every page. Clicking this button will lead you to the GitHub
web editor where you can propose changes to the corresponding page.

Please remember to first check the [latest version](https://netplan.readthedocs.io/en/latest/)
of our documentation and make your proposal based on that revision.

## Contributing on GitHub

If you want to follow a Git development workflow, you can also check out the
[Netplan repository](https://github.com/canonical/netplan) and contribute your
changes as [pull requests](https://github.com/canonical/netplan/pulls), putting
the `documentation` label for better visibility.

## Folder Structure
All the documentation files are located in the `doc/` directory. The `doc/` directory contains sub-directories corresponding to different Diataxis sections. So you should find the following folders inside the `doc/` directory:
* `tutorial`
* `explanation`
* `howto`
* `reference`

If you're adding a new article, ensure you include it in the appropriate Diataxis directory. You can read about [how Ubuntu implements Diataxis for documentation](https://ubuntu.com/blog/diataxis-a-new-foundation-for-canonical-documentation).

## How to Build the Documentation
These steps will show you how to build the documentation on your local machine.
1. To build this documentation, first create a fork of the [Netplan repository](https://github.com/canonical/netplan) and clone that into your machine. For example:
    ```shell
    git clone git@github.com:ade555/netplan.git
    ```
2. Navigate to the `doc/` directory as you'll mostly be working here. Open this directory in your code editor.

3. Install `make` on your machine if you don't have it.
    ```shell
    sudo apt-get install make
    ```
    **NOTE**: The `make` command is compatible with Unix systems. If you're on Windows, you can [install Ubuntu with WSL by following this guide](https://github.com/canonical/open-documentation-academy/blob/main/getting-started/start_with_WSL.md).

4. Within the `doc/` directory, run this command to build and serve the documentation:
    ```shell
    make run
    ```
    This command will install all the necessary packages and set up a Python virtual environment inside the `doc/.sphinx/` directory. 

    After you run the command, the documentation will be served on your system's local machine via `http://127.0.0.1:8000`.

    You can also find the HTML files in the `.build/` directory.

    We use the autobuild module so that any edits you make (and save) as you work will be applied and the documentation refreshed immediately.

## Documentation Format
The Netplan documentation is built with Sphinx using some Restructured Text formatting and Markdown. If you're new to Restructured Text, read our [style guide on how we use it at Ubuntu](https://canonical-documentation-with-sphinx-and-readthedocscom.readthedocs-hosted.com/style-guide/).
We also use our Sphinx documentation starter pack for our documentation. You can [read about it](https://github.com/canonical/sphinx-docs-starter-pack) to properly understand how it works.