pub mod apply;
pub mod generate;
pub mod get;
pub mod info;
pub mod ip;
pub mod migrate;
pub mod set;
pub mod sriov_rebind;
pub mod status;
pub mod try_command;

use anyhow::Result;

/// Run the netplan subcommand `cmd` with the arguments left over from the
/// top-level parse.
pub fn run(cmd: &str, argv0: &str, args: &[String]) -> Result<i32> {
    match cmd {
        "apply" => apply::command(argv0, args),
        "generate" => generate::command(argv0, args),
        "get" => get::command(argv0, args),
        "info" => info::command(argv0, args),
        "ip" => ip::command(argv0, args),
        "migrate" => migrate::command(argv0, args),
        "set" => set::command(argv0, args),
        "rebind" => sriov_rebind::command(argv0, args),
        "status" => status::command(argv0, args),
        "try" => try_command::command(argv0, args),
        _ => unreachable!("argparse only accepts known subcommands"),
    }
}
