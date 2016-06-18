#pragma once

void safe_mkdir_p_dir(const char* file_path);
void g_string_free_to_file(GString* s, const char* rootdir, const char* path, const char* suffix);
