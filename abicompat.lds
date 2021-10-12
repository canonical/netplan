SECTIONS
{
  .data.abi_compat : {
    netdefs = global_state + SIZEOF(netdefs_offset) - 8;
    netdefs_ordered = global_state + SIZEOF(netdefs_ordered_offset) - 8;
    ovs_settings_global = global_state + SIZEOF(ovs_settings_offset) - 8;
    global_backend = global_state + SIZEOF(global_backend_offset) - 8;
  }
}
INSERT AFTER .data;
