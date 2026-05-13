const std = @import("std");
const builtin = @import("builtin");
const python = @import("python");
const utils = @import("utils");
const build_options = @import("build_options");

const log = std.log.scoped(.lift_main);

pub const version = build_options.version;

pub const MainError = error{
    AppDirectoryNotFound,
    InvalidConfig,
    OutOfMemory,
} || python.PythonError;

// comptime 路径组件定义
const PathComponents = struct {
    pub const lib = "lib";
    pub const app = "app";
    pub const python3 = "python3";
    pub const site_packages = "site-packages";
};

// comptime 构建路径
const APP_DIR_PARTS = &.{ "..", PathComponents.lib, PathComponents.app };
const SITE_PACKAGES_PARTS = &.{ "..", PathComponents.lib, PathComponents.python3, PathComponents.site_packages };
const LIB_DIR_PARTS = &.{ "..", PathComponents.lib };

// comptime 配置
const DEFAULT_PYTHON_VERSION = "3.11";

pub const AppContext = struct {
    allocator: std.mem.Allocator,
    runtime: ?python.PythonRuntime,
    exe_dir: []const u8,

    const Self = @This();

    pub fn init(allocator: std.mem.Allocator) MainError!Self {
        const io = std.Io.Threaded.global_single_threaded.io();

        const exe_path = std.process.executablePathAlloc(io, allocator) catch |err| {
            log.err("Failed to get executable path: {s}", .{@errorName(err)});
            return MainError.InvalidConfig;
        };
        defer allocator.free(exe_path);

        const exe_dir = std.fs.path.dirname(exe_path) orelse ".";
        const exe_dir_copy = allocator.dupe(u8, exe_dir) catch return MainError.OutOfMemory;
        errdefer allocator.free(exe_dir_copy);

        return Self{
            .allocator = allocator,
            .runtime = null,
            .exe_dir = exe_dir_copy,
        };
    }

    pub fn deinit(self: *Self) void {
        if (self.runtime) |*rt| {
            rt.deinit();
        }
        self.allocator.free(self.exe_dir);
        self.* = undefined;
    }

    pub fn initializePython(self: *Self) MainError!void {
        const lib_path = blk: {
            // 优先使用默认版本
            const path = python.resolvePythonLibPath(
                self.allocator,
                self.exe_dir,
                DEFAULT_PYTHON_VERSION,
            ) catch |err| {
                if (err == python.PythonError.FileNotFound) {
                    // 默认版本未找到，尝试动态检测系统 Python 版本
                    log.warn("Python {s} not found, detecting system version...", .{DEFAULT_PYTHON_VERSION});
                    const detected_ver = python.detectSystemPythonVersion(self.allocator) catch |detect_err| {
                        log.err("Failed to detect system Python version: {s}", .{@errorName(detect_err)});
                        return detect_err;
                    };
                    defer self.allocator.free(detected_ver);

                    log.info("Detected Python version: {s}", .{detected_ver});
                    const detected_path = python.resolvePythonLibPath(
                        self.allocator,
                        self.exe_dir,
                        detected_ver,
                    ) catch |resolve_err| {
                        log.err("Failed to resolve detected Python library: {s}", .{@errorName(resolve_err)});
                        return resolve_err;
                    };
                    break :blk detected_path;
                }
                log.err("Failed to resolve Python library: {s}", .{@errorName(err)});
                return err;
            };
            break :blk path;
        };
        defer self.allocator.free(lib_path);

        log.info("Loading Python from: {s}", .{lib_path});

        var runtime = try python.PythonRuntime.init(self.allocator, lib_path);
        errdefer runtime.deinit();

        try runtime.initialize();

        const temp_dir = blk: {
            break :blk utils.getTempDir(self.allocator) catch |err| {
                log.warn("Failed to get temp dir: {s}, using fallback", .{@errorName(err)});
                break :blk null;
            };
        };
        if (temp_dir) |td| {
            defer self.allocator.free(td);
            runtime.setupExceptionHook(td);
            runtime.setPycachePrefix(td);
        } else {
            runtime.setupExceptionHook(null);
            runtime.setPycachePrefix(null);
        }

        self.runtime = runtime;
        log.info("Python initialized successfully", .{});
    }
};

fn getAppDirectory(allocator: std.mem.Allocator, exe_dir: []const u8) MainError![]const u8 {
    const io = std.Io.Threaded.global_single_threaded.io();
    const dir = std.Io.Dir.cwd();

    // 使用 comptime 路径组件构建完整路径
    var path_parts: [1 + APP_DIR_PARTS.len][]const u8 = undefined;
    path_parts[0] = exe_dir;
    inline for (APP_DIR_PARTS, 0..) |part, i| {
        path_parts[1 + i] = part;
    }

    const app_path = std.fs.path.join(allocator, &path_parts) catch return MainError.OutOfMemory;
    errdefer allocator.free(app_path);

    dir.access(io, app_path, .{}) catch {
        return MainError.AppDirectoryNotFound;
    };
    return app_path;
}

fn detectSitePackagesPath(
    allocator: std.mem.Allocator,
    base_dir: []const u8,
) MainError![]const u8 {
    const io = std.Io.Threaded.global_single_threaded.io();
    const dir = std.Io.Dir.cwd();

    // 使用 comptime 路径组件构建完整路径
    var path_parts: [1 + SITE_PACKAGES_PARTS.len][]const u8 = undefined;
    path_parts[0] = base_dir;
    inline for (SITE_PACKAGES_PARTS, 0..) |part, i| {
        path_parts[1 + i] = part;
    }

    const path = std.fs.path.join(allocator, &path_parts) catch return MainError.OutOfMemory;
    errdefer allocator.free(path);

    dir.access(io, path, .{}) catch {
        allocator.free(path);
        return MainError.AppDirectoryNotFound;
    };
    return path;
}

fn runApplication(ctx: *AppContext) MainError!void {
    const runtime = ctx.runtime.?;
    const allocator = ctx.allocator;

    const app_path = try getAppDirectory(allocator, ctx.exe_dir);
    defer allocator.free(app_path);

    const base_dir = std.fs.path.dirname(app_path) orelse ctx.exe_dir;

    const site_packages = try detectSitePackagesPath(allocator, base_dir);
    defer allocator.free(site_packages);

    log.info("Using site-packages: {s}", .{site_packages});

    runtime.addToSysPath(base_dir) catch |err| {
        log.err("Failed to add base dir: {s}", .{@errorName(err)});
        return err;
    };

    runtime.addToSysPath(app_path) catch |err| {
        log.err("Failed to add app path: {s}", .{@errorName(err)});
        return err;
    };

    runtime.addToSysPath(site_packages) catch |err| {
        log.warn("Failed to add site-packages: {s}", .{@errorName(err)});
    };

    const argv = &[_][]const u8{ "lift", "app.main" };
    runtime.setSysArgv(argv) catch |err| {
        log.warn("Failed to set sys.argv: {s}", .{@errorName(err)});
    };

    log.info("Running module: app.main", .{});

    runtime.runModule("app.main") catch |err| {
        log.err("Module 'app.main' execution failed: {s}", .{@errorName(err)});
        return err;
    };

    log.info("Application completed successfully", .{});
}

pub fn panic(msg: []const u8, error_return_trace: ?*std.builtin.StackTrace, _: ?usize) noreturn {
    // Use page_allocator in panic handler: smp_allocator may be unreliable during panic
    _ = utils.CrashHandler.writeCrashLog(std.heap.page_allocator, msg, error_return_trace) catch {};
    std.debug.panicExtra(null, "lift panic: {s}", .{msg});
}

pub fn main() MainError!void {
    const allocator = std.heap.smp_allocator;

    var ctx = try AppContext.init(allocator);
    defer ctx.deinit();

    try ctx.initializePython();
    try runApplication(&ctx);

    log.info("Application finished", .{});
}

test "AppContext init" {
    var ctx = try AppContext.init(std.testing.allocator);
    defer ctx.deinit();
    try std.testing.expect(ctx.runtime == null);
}

// comptime 验证测试
comptime {
    // 验证路径组件
    std.debug.assert(APP_DIR_PARTS.len == 3);
    std.debug.assert(SITE_PACKAGES_PARTS.len == 4);
}
