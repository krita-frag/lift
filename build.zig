const std = @import("std");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});

    // Get version from git or use default
    const version = getVersion(b);

    // Create options module for version injection
    const options = b.addOptions();
    options.addOption([]const u8, "version", version);
    options.addOption([]const u8, "python_version", "3.11");

    // Utils 模块 - 共享工具模块
    const utils_mod = b.addModule("utils", .{
        .root_source_file = b.path("src/utils.zig"),
        .target = target,
    });

    // 创建一个统一的 python 模块
    const python_mod = b.addModule("python", .{
        .root_source_file = b.path("src/python.zig"),
        .target = target,
    });
    python_mod.addImport("utils", utils_mod);

    // 主可执行文件
    const exe = b.addExecutable(.{
        .name = "lift",
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/main.zig"),
            .target = target,
            .optimize = optimize,
            .link_libc = true,
            .imports = &.{
                .{ .name = "python", .module = python_mod },
                .{ .name = "utils", .module = utils_mod },
                .{ .name = "build_options", .module = options.createModule() },
            },
        }),
    });

    // 链接 Python 库
    linkPythonLib(b, exe, target);

    b.installArtifact(exe);

    const run_step = b.step("run", "Run the app");
    const run_cmd = b.addRunArtifact(exe);
    run_step.dependOn(&run_cmd.step);
    run_cmd.step.dependOn(b.getInstallStep());

    if (b.args) |args| {
        run_cmd.addArgs(args);
    }

    // 测试
    const test_step = b.step("test", "Run tests");

    // Python module tests
    const python_tests = b.addTest(.{
        .name = "python_tests",
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/python.zig"),
            .target = target,
            .optimize = optimize,
            .link_libc = true,
            .imports = &.{
                .{ .name = "utils", .module = utils_mod },
            },
        }),
    });
    linkPythonLib(b, python_tests, target);

    const run_python_tests = b.addRunArtifact(python_tests);
    test_step.dependOn(&run_python_tests.step);

    // Main module tests
    const main_tests = b.addTest(.{
        .name = "main_tests",
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/main.zig"),
            .target = target,
            .optimize = optimize,
            .link_libc = true,
            .imports = &.{
                .{ .name = "python", .module = python_mod },
                .{ .name = "utils", .module = utils_mod },
                .{ .name = "build_options", .module = options.createModule() },
            },
        }),
    });
    linkPythonLib(b, main_tests, target);

    const run_main_tests = b.addRunArtifact(main_tests);
    test_step.dependOn(&run_main_tests.step);
}

/// 链接 Python 库（仅编译时使用）
/// 注意：Python 库路径的查找逻辑在 python.zig 中实现，这里只处理编译时链接
/// Windows: 链接 libexec/python3/ 下的 embeddable Python
/// Linux/macOS: 运行时动态加载，编译时不链接
fn linkPythonLib(b: *std.Build, compile_step: *std.Build.Step.Compile, target: std.Build.ResolvedTarget) void {
    if (target.result.os.tag == .windows) {
        // Windows: 需要链接 embeddable Python
        // embeddable Python 的库文件名为 python3xx.lib (如 python311.lib)
        const python_lib_name = b.fmt("python{s}", .{"311"}); // 匹配 pyproject.toml 中的 3.11
        compile_step.root_module.addLibraryPath(b.path("libexec/python3"));
        compile_step.root_module.linkSystemLibrary(python_lib_name, .{});
        std.log.info("Windows: linking against embeddable Python lib: {s}", .{python_lib_name});
    }
    // Linux/macOS: 运行时动态加载，编译时不需要链接
}

fn getVersion(b: *std.Build) []const u8 {
    const io = std.Io.Threaded.global_single_threaded.io();
    const result = std.process.run(b.allocator, io, .{
        .argv = &.{ "git", "describe", "--tags", "--always", "--dirty" },
        .cwd = if (b.build_root.path) |p| .{ .path = p } else .inherit,
    }) catch return "0.1.0-dev";

    if (result.term == .exited and result.term.exited == 0) {
        const version = std.mem.trim(u8, result.stdout, " \n\r\t");
        if (version.len > 0) return b.dupe(version);
    }

    return "0.1.0-dev";
}
