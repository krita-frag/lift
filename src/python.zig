const std = @import("std");
const builtin = @import("builtin");

const log = std.log.scoped(.lift_python);

pub const PyObject = opaque {};

pub const PythonError = error{
    OutOfMemory,
    FailedToLoadLibrary,
    SymbolNotFound,
    PythonExecutionFailed,
    PythonImportFailed,
    PythonAPIFailed,
    InvalidConfig,
    FileNotFound,
    PythonNotInitialized,
    PythonVersionNotDetected,
    EntryPointNotFound,
};

pub const PythonCApi = struct {
    Py_Initialize: *const fn () callconv(.c) void,
    Py_Finalize: *const fn () callconv(.c) void,
    Py_IsInitialized: *const fn () callconv(.c) c_int,

    PyErr_Print: *const fn () callconv(.c) void,
    PyErr_Clear: *const fn () callconv(.c) void,
    PyErr_Occurred: *const fn () callconv(.c) ?*PyObject,

    Py_DecRef: *const fn (*PyObject) callconv(.c) void,
    Py_IncRef: *const fn (*PyObject) callconv(.c) void,

    PyUnicode_FromString: *const fn ([*:0]const u8) callconv(.c) ?*PyObject,
    PyUnicode_AsUTF8: *const fn (*PyObject) callconv(.c) ?[*:0]const u8,

    PyList_New: *const fn (isize) callconv(.c) ?*PyObject,
    PyList_SetItem: *const fn (*PyObject, isize, *PyObject) callconv(.c) c_int,
    PyList_Insert: *const fn (*PyObject, isize, *PyObject) callconv(.c) c_int,

    PyRun_SimpleString: *const fn ([*:0]const u8) callconv(.c) c_int,
    PyRun_SimpleFile: *const fn (?*anyopaque, [*:0]const u8) callconv(.c) c_int,

    PySys_GetObject: *const fn ([*:0]const u8) callconv(.c) ?*PyObject,
    PySys_SetObject: *const fn ([*:0]const u8, *PyObject) callconv(.c) c_int,

    Py_GetVersion: *const fn () callconv(.c) [*:0]const u8,
};

extern "c" fn popen(command: [*:0]const u8, mode: [*:0]const u8) ?*anyopaque;
extern "c" fn pclose(stream: ?*anyopaque) c_int;
extern "c" fn fgets(buf: [*]u8, size: c_int, stream: ?*anyopaque) ?[*:0]u8;

/// 检测系统 Python 版本
pub fn detectSystemPythonVersion(allocator: std.mem.Allocator) PythonError![]const u8 {
    const cmd = "python3 -c 'import sys; print(\"{}.{}\".format(sys.version_info.major, sys.version_info.minor))'";

    const fp = popen(cmd, "r") orelse {
        log.warn("Failed to popen python3", .{});
        return PythonError.PythonVersionNotDetected;
    };
    defer _ = pclose(fp);

    var buf: [64]u8 = undefined;
    const result = fgets(&buf, buf.len, fp);
    if (result == null) {
        log.warn("Failed to read python3 version output", .{});
        return PythonError.PythonVersionNotDetected;
    }

    const version = std.mem.trim(u8, buf[0..std.mem.indexOfScalar(u8, &buf, 0).?], " \n\r\t");
    if (version.len > 0) {
        return allocator.dupe(u8, version) catch return PythonError.OutOfMemory;
    }

    return PythonError.PythonVersionNotDetected;
}

extern "c" fn fopen(path: [*:0]const u8, mode: [*:0]const u8) ?*anyopaque;
extern "c" fn fclose(fp: *anyopaque) c_int;

pub const PythonRuntime = struct {
    allocator: std.mem.Allocator,
    lib: ?std.DynLib,
    api: PythonCApi,
    initialized: bool,

    const Self = @This();

    pub fn init(allocator: std.mem.Allocator, lib_path: []const u8) PythonError!Self {
        var lib = std.DynLib.open(lib_path) catch {
            log.err("Failed to load Python library: {s}", .{lib_path});
            return PythonError.FailedToLoadLibrary;
        };

        var api: PythonCApi = undefined;
        inline for (@typeInfo(PythonCApi).@"struct".fields) |field| {
            @field(api, field.name) = lib.lookup(field.type, field.name) orelse {
                log.err("Symbol not found: {s}", .{field.name});
                return PythonError.SymbolNotFound;
            };
        }

        return Self{
            .allocator = allocator,
            .lib = lib,
            .api = api,
            .initialized = false,
        };
    }

    pub fn deinit(self: *Self) void {
        if (self.initialized) {
            self.api.Py_Finalize();
            self.initialized = false;
        }
        if (self.lib) |*lib| {
            lib.close();
            self.lib = null;
        }
        self.* = undefined;
    }

    pub fn initialize(self: *Self) PythonError!void {
        if (self.initialized) return;

        self.api.Py_Initialize();
        self.initialized = true;

        const version = std.mem.span(self.api.Py_GetVersion());
        log.info("Python initialized: {s}", .{version});
    }

    pub fn addToSysPath(self: *const Self, path: []const u8) PythonError!void {
        if (!self.initialized) {
            log.err("Cannot add to sys.path: Python not initialized", .{});
            return PythonError.PythonNotInitialized;
        }

        const path_z = allocPrintZ(self.allocator, "{s}", .{path}) catch return PythonError.OutOfMemory;
        defer self.allocator.free(path_z);

        const path_obj = self.api.PyUnicode_FromString(path_z.ptr) orelse {
            if (self.api.PyErr_Occurred() != null) self.api.PyErr_Print();
            log.err("Failed to create Python string from path: {s}", .{path});
            return PythonError.PythonAPIFailed;
        };
        defer self.api.Py_DecRef(path_obj);

        const sys_path = self.api.PySys_GetObject("path") orelse {
            if (self.api.PyErr_Occurred() != null) self.api.PyErr_Print();
            log.err("Failed to get sys.path object", .{});
            return PythonError.PythonAPIFailed;
        };

        if (self.api.PyList_Insert(sys_path, 0, path_obj) != 0) {
            if (self.api.PyErr_Occurred() != null) self.api.PyErr_Print();
            log.err("Failed to insert path into sys.path: {s}", .{path});
            return PythonError.PythonExecutionFailed;
        }

        log.info("Added to sys.path: {s}", .{path});
    }

    pub fn setupExceptionHook(self: *const Self, log_dir: ?[]const u8) void {
        if (!self.initialized) return;

        if (log_dir) |ld| {
            self.setupExceptionHookWithLog(ld);
        } else {
            self.setupExceptionHookBasic();
        }
    }

    fn setupExceptionHookWithLog(self: *const Self, log_dir: []const u8) void {
        const escaped = allocPrintZ(self.allocator, "{s}", .{log_dir}) catch {
            log.warn("Failed to alloc log dir for exception hook", .{});
            self.setupExceptionHookBasic();
            return;
        };
        defer self.allocator.free(escaped);

        const code = allocPrintZ(self.allocator,
            \\import sys, os, traceback
            \\_log_dir = r'{s}'
            \\def _lift_excepthook(exc_type, exc_value, exc_traceback):
            \\    error_msg = ''.join(traceback.format_exception(exc_type, exc_value, exc_traceback))
            \\    print('ERROR:', error_msg, file=sys.stderr, flush=True)
            \\    try:
            \\        os.makedirs(_log_dir, exist_ok=True)
            \\        log_path = os.path.join(_log_dir, 'python_error.log')
            \\        with open(log_path, 'a', encoding='utf-8') as f:
            \\            f.write(error_msg + '\\n')
            \\    except Exception:
            \\        pass
            \\sys.excepthook = _lift_excepthook
        , .{escaped}) catch {
            log.warn("Failed to alloc exception hook code", .{});
            self.setupExceptionHookBasic();
            return;
        };
        defer self.allocator.free(code);

        self.runString(code) catch |err| {
            log.warn("Failed to setup exception hook: {s}", .{@errorName(err)});
        };
    }

    fn setupExceptionHookBasic(self: *const Self) void {
        const code =
            \\import sys, traceback
            \\def _lift_excepthook(exc_type, exc_value, exc_traceback):
            \\    trace = '\\n'.join(traceback.format_exception(exc_type, exc_value, exc_traceback))
            \\    sys.stderr.write(trace + '\\n')
            \\    sys.stderr.flush()
            \\sys.excepthook = _lift_excepthook
        ;
        self.runString(code) catch |err| {
            log.warn("Failed to setup basic exception hook: {s}", .{@errorName(err)});
        };
    }

    pub fn setPycachePrefix(self: *const Self, prefix: ?[]const u8) void {
        if (prefix == null) return;
        const cache_prefix = prefix.?;

        const code = allocPrintZ(self.allocator,
            \\import os
            \\os.makedirs(r'{s}', exist_ok=True)
            \\os.environ['PYTHONPYCACHEPREFIX'] = r'{s}'
        , .{ cache_prefix, cache_prefix }) catch {
            log.warn("Failed to set pycache prefix: path too long", .{});
            return;
        };
        defer self.allocator.free(code);

        self.runString(code) catch |err| {
            log.warn("Failed to set pycache prefix: {s}", .{@errorName(err)});
            return;
        };

        log.info("Set PYTHONPYCACHEPREFIX to: {s}", .{cache_prefix});
    }

    pub fn setSysArgv(self: *const Self, argv: []const []const u8) PythonError!void {
        if (!self.initialized) return PythonError.PythonAPIFailed;

        const list = self.api.PyList_New(@intCast(argv.len)) orelse {
            if (self.api.PyErr_Occurred() != null) self.api.PyErr_Print();
            return PythonError.OutOfMemory;
        };
        errdefer self.api.Py_DecRef(list);

        for (argv, 0..) |arg, i| {
            const arg_z = allocPrintZ(self.allocator, "{s}", .{arg}) catch return PythonError.OutOfMemory;
            defer self.allocator.free(arg_z);

            const obj = self.api.PyUnicode_FromString(arg_z.ptr) orelse {
                if (self.api.PyErr_Occurred() != null) self.api.PyErr_Print();
                return PythonError.OutOfMemory;
            };
            if (self.api.PyList_SetItem(list, @intCast(i), obj) != 0) {
                self.api.Py_DecRef(obj);
                if (self.api.PyErr_Occurred() != null) self.api.PyErr_Print();
                return PythonError.PythonExecutionFailed;
            }
        }

        if (self.api.PySys_SetObject("argv", list) != 0) {
            if (self.api.PyErr_Occurred() != null) self.api.PyErr_Print();
            return PythonError.PythonExecutionFailed;
        }
    }

    pub fn runModule(self: *const Self, module_name: []const u8) PythonError!void {
        if (!self.initialized) return PythonError.PythonAPIFailed;

        const code = allocPrintZ(self.allocator,
            \\import runpy, sys
            \\sys.argv = ['{s}']
            \\runpy.run_module('{s}', run_name='__main__')
        , .{ module_name, module_name }) catch return PythonError.OutOfMemory;
        defer self.allocator.free(code);

        const result = self.api.PyRun_SimpleString(code.ptr);
        if (result != 0) {
            if (self.api.PyErr_Occurred() != null) {
                self.api.PyErr_Print();
            }
            return PythonError.PythonExecutionFailed;
        }
    }

    pub fn runScriptFile(self: *const Self, script_path: []const u8) PythonError!void {
        if (!self.initialized) return PythonError.PythonAPIFailed;

        const path_z = allocPrintZ(self.allocator, "{s}", .{script_path}) catch return PythonError.OutOfMemory;
        defer self.allocator.free(path_z);

        const fp = fopen(path_z.ptr, "r") orelse {
            log.err("Failed to open script file: {s}", .{script_path});
            return PythonError.FileNotFound;
        };
        defer _ = fclose(fp);

        const result = self.api.PyRun_SimpleFile(fp, path_z.ptr);
        if (result != 0) {
            if (self.api.PyErr_Occurred() != null) {
                self.api.PyErr_Print();
            }
            return PythonError.PythonExecutionFailed;
        }
    }

    pub fn runString(self: *const Self, code: [:0]const u8) PythonError!void {
        if (!self.initialized) return PythonError.PythonAPIFailed;

        const result = self.api.PyRun_SimpleString(code.ptr);
        if (result != 0) {
            if (self.api.PyErr_Occurred() != null) {
                self.api.PyErr_Print();
            }
            return PythonError.PythonExecutionFailed;
        }
    }
};

pub fn resolvePythonLibPath(
    allocator: std.mem.Allocator,
    exe_dir: []const u8,
    py_ver: []const u8,
) PythonError![]const u8 {
    const io = std.Io.Threaded.global_single_threaded.io();
    const dir = std.Io.Dir.cwd();

    // 获取备选库名称列表
    const lib_names = try getPythonLibSearchNames(allocator, py_ver);
    defer {
        for (lib_names) |name| {
            allocator.free(name);
        }
        allocator.free(lib_names);
    }

    // Platform-specific search order:
    // - Windows: 优先查找打包目录（embeddable Python）
    // - Linux/macOS: 优先查找系统路径（使用系统 Python）

    if (builtin.target.os.tag == .windows) {
        // Windows: 优先查打包目录
        const bundled_paths = try getBundledPaths(allocator, exe_dir);
        defer freeBundledPaths(allocator, bundled_paths);
        for (bundled_paths) |p| {
            for (lib_names) |lib_name| {
                const full_path = try std.fs.path.join(allocator, &.{ p, lib_name });
                errdefer allocator.free(full_path);

                dir.access(io, full_path, .{}) catch {
                    allocator.free(full_path);
                    continue;
                };
                return full_path;
            }
        }
    } else {
        // Linux/macOS: 优先查系统路径
        const system_paths = try getSystemPaths(allocator);
        defer freeSystemPaths(allocator, system_paths);
        for (system_paths) |p| {
            for (lib_names) |lib_name| {
                const full_path = try std.fs.path.join(allocator, &.{ p, lib_name });
                errdefer allocator.free(full_path);

                log.debug("Checking: {s}", .{full_path});

                dir.access(io, full_path, .{}) catch {
                    log.debug("  Not found: {s}", .{full_path});
                    allocator.free(full_path);
                    continue;
                };
                log.info("Found Python library: {s}", .{full_path});
                return full_path;
            }
        }

        // Fallback: 查找打包目录（用于自定义部署场景）
        const bundled_paths = try getBundledPaths(allocator, exe_dir);
        defer freeBundledPaths(allocator, bundled_paths);
        for (bundled_paths) |p| {
            for (lib_names) |lib_name| {
                const full_path = try std.fs.path.join(allocator, &.{ p, lib_name });
                errdefer allocator.free(full_path);

                log.debug("Checking: {s}", .{full_path});

                dir.access(io, full_path, .{}) catch {
                    log.debug("  Not found: {s}", .{full_path});
                    allocator.free(full_path);
                    continue;
                };
                log.info("Found Python library: {s}", .{full_path});
                return full_path;
            }
        }
    }

    return PythonError.FileNotFound;
}

// 定义 bundled 路径的组件
const BUNDLED_PATH_COMPONENTS = &[_][]const []const u8{
    &.{ "lib", "python3", "bin" },
    &.{"lib"},
};

fn getBundledPaths(allocator: std.mem.Allocator, exe_dir: []const u8) ![]const []const u8 {
    const base_dir = std.fs.path.dirname(exe_dir) orelse ".";

    const path_count = BUNDLED_PATH_COMPONENTS.len;

    const paths = try allocator.alloc([]const u8, path_count);
    errdefer allocator.free(paths);

    inline for (BUNDLED_PATH_COMPONENTS, 0..) |components, i| {
        var path_parts: [1 + components.len][]const u8 = undefined;
        path_parts[0] = base_dir;
        for (components, 0..) |comp, j| {
            path_parts[1 + j] = comp;
        }
        paths[i] = try std.fs.path.join(allocator, &path_parts);
    }

    return paths;
}

fn freeBundledPaths(allocator: std.mem.Allocator, paths: []const []const u8) void {
    for (paths) |p| {
        allocator.free(p);
    }
    allocator.free(paths);
}

const MACOS_SYSTEM_PATHS = &.{
    "/opt/homebrew/Frameworks/Python.framework/Versions/Current/lib",
    "/opt/homebrew/lib",
    "/Library/Frameworks/Python.framework/Versions/Current/lib",
    "/System/Library/Frameworks/Python.framework/Versions/Current/lib",
    "/usr/local/lib",
    "/usr/lib",
};

const LINUX_SYSTEM_PATHS = &.{
    "/usr/lib/x86_64-linux-gnu",
    "/usr/local/lib",
    "/usr/lib",
};

const SYSTEM_PATHS = switch (builtin.target.os.tag) {
    .macos => MACOS_SYSTEM_PATHS,
    else => LINUX_SYSTEM_PATHS,
};

/// Get system Python library paths
/// Uses comptime-defined fallback paths for macOS and Linux
fn getSystemPaths(allocator: std.mem.Allocator) ![]const []const u8 {
    const fallback_paths = SYSTEM_PATHS;

    const paths = try allocator.alloc([]const u8, fallback_paths.len);
    inline for (fallback_paths, 0..) |p, i| {
        paths[i] = try allocator.dupe(u8, p);
    }
    return paths;
}

fn freeSystemPaths(allocator: std.mem.Allocator, paths: []const []const u8) void {
    for (paths) |p| {
        allocator.free(p);
    }
    allocator.free(paths);
}

fn getPythonLibName(allocator: std.mem.Allocator, py_ver: []const u8) ![]const u8 {
    return switch (builtin.target.os.tag) {
        .windows => try std.fmt.allocPrint(allocator, "python{s}.dll", .{py_ver}),
        .macos => try std.fmt.allocPrint(allocator, "libpython{s}.dylib", .{py_ver}),
        else => try std.fmt.allocPrint(allocator, "libpython{s}.so", .{py_ver}),
    };
}

const LibNameTemplate = struct {
    fmt: []const u8,
    ver_arg: enum { specific, generic, none },
};

const WINDOWS_TEMPLATES = &[_]LibNameTemplate{
    .{ .fmt = "python{s}.dll", .ver_arg = .specific },
    .{ .fmt = "python{s}.dll", .ver_arg = .generic },
    .{ .fmt = "python3.dll", .ver_arg = .none },
};

const MACOS_TEMPLATES = &[_]LibNameTemplate{
    .{ .fmt = "libpython{s}.dylib", .ver_arg = .specific },
    .{ .fmt = "libpython{s}.dylib", .ver_arg = .generic },
    .{ .fmt = "libpython3.dylib", .ver_arg = .none },
};

const LINUX_TEMPLATES = &[_]LibNameTemplate{
    .{ .fmt = "libpython{s}.so", .ver_arg = .specific },
    .{ .fmt = "libpython{s}.so.1.0", .ver_arg = .specific },
    .{ .fmt = "libpython{s}.so", .ver_arg = .generic },
    .{ .fmt = "libpython3.so", .ver_arg = .none },
};

const PLATFORM_TEMPLATES = switch (builtin.target.os.tag) {
    .windows => WINDOWS_TEMPLATES,
    .macos => MACOS_TEMPLATES,
    else => LINUX_TEMPLATES,
};

fn getPythonLibSearchNames(allocator: std.mem.Allocator, py_ver: []const u8) ![]const []const u8 {
    const count = PLATFORM_TEMPLATES.len;

    const names = try allocator.alloc([]const u8, count);
    errdefer allocator.free(names);

    inline for (PLATFORM_TEMPLATES, 0..) |template, i| {
        names[i] = switch (template.ver_arg) {
            .specific => try std.fmt.allocPrint(allocator, template.fmt, .{py_ver}),
            .generic => try std.fmt.allocPrint(allocator, template.fmt, .{"3"}),
            .none => try allocator.dupe(u8, template.fmt),
        };
    }

    return names;
}

fn allocPrintZ(allocator: std.mem.Allocator, comptime fmt: []const u8, args: anytype) ![:0]const u8 {
    return std.fmt.allocPrintSentinel(allocator, fmt, args, 0);
}
