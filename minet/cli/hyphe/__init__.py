# =============================================================================
# Minet Hyphe CLI Action
# =============================================================================
#
# Logic of the `hyphe` action.
#


def hyphe_action(cli_args):

    if cli_args.hyphe_action == 'declare':
        from minet.cli.hyphe.declare import hyphe_declare_action

        hyphe_declare_action(cli_args)

    elif cli_args.hyphe_action == 'dump':
        from minet.cli.hyphe.dump import hyphe_dump_action

        hyphe_dump_action(cli_args)
