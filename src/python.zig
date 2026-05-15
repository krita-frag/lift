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
    const cmd = "python3 -c \"import sys; print('{}.{}'.format(sys.version_info.major, sys.version_info.minor))\"";

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

    const end_pos = std.mem.indexOfScalar(u8, &buf, 0) orelse buf.len;
    const version = std.mem.trim(u8, buf[0..end_pos], " \n\r\t");
    if (version.len > 0) {
        return allocator.dupe(u8, version) catch return PythonError.OutOfMemory;
    }

    return PythonError.PythonVersionNotDetected;
}

extern "c" fn fopen(path: [*:0]const u8, mode: [*:0]const u8) ?*anyopaque;
extern "c" fn fclose(fp: *anyopaque) c_int;

// 平台特定的动态库加载
const DynLib = switch (builtin.os.tag) {
    .windows => WindowsDynLib,
    else => std.DynLib,
};

// Windows 动态库实现
const WindowsDynLib = struct {
    handle: std.os.windows.HMODULE,

    const Self = @This();

    pub fn open(path: []const u8) !Self {
        const path_w = try std.os.windows.cStrToPrefixedFileW(path);
        const handle = std.os.windows.LoadLibraryW(&path_w.data) orelse {
            return PythonError.FailedToLoadLibrary;
        };
        return Self{ .handle = handle };
    }

    pub fn close(self: *Self) void {
        if (self.handle) |h| {
            _ = std.os.windows.FreeLibrary(h);
            self.handle = null;
        }
    }

    pub fn lookup(self: *const Self, comptime T: type, name: [:0]const u8) ?T {
        const proc = std.os.windows.GetProcAddress(self.handle, name) orelse return null;
        return @ptrCast(proc);
    }
};

pub const PythonRuntime = struct {
    allocator: std.mem.Allocator,
    lib: ?DynLib,
    api: PythonCApi,
    initialized: bool,

    const Self = @This();

    pub fn init(allocator: std.mem.Allocator, lib_path: []const u8) PythonError!Self {
        var lib = DynLib.open(lib_path) catch {
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
            log.err("Failed to create sys.argv list", .{});
            return PythonError.PythonAPIFailed;
        };

        for (argv, 0..) |arg, i| {
            const arg_z = allocPrintZ(self.allocator, "{s}", .{arg}) catch return PythonError.OutOfMemory;
            defer self.allocator.free(arg_z);

            const arg_obj = self.api.PyUnicode_FromString(arg_z.ptr) orelse {
                if (self.api.PyErr_Occurred() != null) self.api.PyErr_Print();
                log.err("Failed to create Python string for argv[{d}]", .{i});
                return PythonError.PythonAPIFailed;
            };

            // PyList_SetItem steals reference
            if (self.api.PyList_SetItem(list, @intCast(i), arg_obj) != 0) {
                if (self.api.PyErr_Occurred() != null) self.api.PyErr_Print();
                log.err("Failed to set argv[{d}]", .{i});
                return PythonError.PythonAPIFailed;
            }
        }

        if (self.api.PySys_SetObject("argv", list) != 0) {
            if (self.api.PyErr_Occurred() != null) self.api.PyErr_Print();
            log.err("Failed to set sys.argv", .{});
            return PythonError.PythonAPIFailed;
        }

        log.info("Set sys.argv with {d} arguments", .{argv.len});
    }

    pub fn runString(self: *const Self, code: [:0]const u8) PythonError!void {
        if (!self.initialized) {
            log.err("Cannot run string: Python not initialized", .{});
            return PythonError.PythonNotInitialized;
        }

        const result = self.api.PyRun_SimpleString(code);
        if (result != 0) {
            if (self.api.PyErr_Occurred() != null) self.api.PyErr_Print();
            log.err("Python execution failed with code: {d}", .{result});
            return PythonError.PythonExecutionFailed;
        }
    }

    pub fn runFile(self: *const Self, file_path: []const u8) PythonError!void {
        if (!self.initialized) {
            log.err("Cannot run file: Python not initialized", .{});
            return PythonError.PythonNotInitialized;
        }

        const path_z = allocPrintZ(self.allocator, "{s}", .{file_path}) catch return PythonError.OutOfMemory;
        defer self.allocator.free(path_z);

        const fp = fopen(path_z.ptr, "r") orelse {
            log.err("Failed to open file: {s}", .{file_path});
            return PythonError.FileNotFound;
        };
        defer _ = fclose(fp);

        const result = self.api.PyRun_SimpleFile(fp, path_z.ptr);
        if (result != 0) {
            if (self.api.PyErr_Occurred() != null) self.api.PyErr_Print();
            log.err("Python file execution failed: {s}", .{file_path});
            return PythonError.PythonExecutionFailed;
        }

        log.info("Successfully executed: {s}", .{file_path});
    }

    pub fn isInitialized(self: *const Self) bool {
        return self.initialized;
    }

    pub fn getVersion(self: *const Self) []const u8 {
        return std.mem.span(self.api.Py_GetVersion());
    }
};

fn allocPrintZ(allocator: std.mem.Allocator, comptime fmt: []const u8, args: anytype) ![:0]u8 {
    const result = try std.fmt.allocPrint(allocator, fmt, args);
    defer allocator.free(result);
    return allocator.dupeZ(u8, result);
}

/// 查找 Python 库路径
pub fn findPythonLibrary(allocator: std.mem.Allocator, lib_dir: []const u8) ![:0]const u8 {
    const lib_path = try std.fs.path.join(allocator, &.{ lib_dir, "libpython3.11.so" });
    defer allocator.free(lib_path);

    std.fs.accessAbsolute(lib_path, .{}) catch {
        log.err("Python library not found: {s}", .{lib_path});
        return PythonError.FileNotFound;
    };

    return allocator.dupeZ(u8, lib_path);
}
