const std = @import("std");
const builtin = @import("builtin");

const log = std.log.scoped(.lift_utils);

const LIFT_TEMP_SUBDIR = "lift";
const DEFAULT_UNIX_TEMP = "/tmp/lift";
const DEFAULT_WIN_TEMP = "C:\\Windows\\Temp\\lift";

pub fn getTempDir(allocator: std.mem.Allocator) ![]const u8 {
    if (std.c.getenv("LIFT_TEMP_DIR")) |dir_ptr| {
        return try allocator.dupe(u8, std.mem.span(dir_ptr));
    }

    switch (builtin.target.os.tag) {
        .windows => {
            inline for (.{ "TEMP", "TMP" }) |env_var| {
                if (std.c.getenv(env_var)) |tmp_ptr| {
                    return std.fs.path.join(allocator, &.{ std.mem.span(tmp_ptr), LIFT_TEMP_SUBDIR });
                }
            }
            return try allocator.dupe(u8, DEFAULT_WIN_TEMP);
        },
        else => {
            if (std.c.getenv("TMPDIR")) |tmp_ptr| {
                return std.fs.path.join(allocator, &.{ std.mem.span(tmp_ptr), LIFT_TEMP_SUBDIR });
            }
            return try allocator.dupe(u8, DEFAULT_UNIX_TEMP);
        },
    }
}

pub const CrashHandler = struct {
    pub fn writeCrashLog(
        allocator: std.mem.Allocator,
        message: []const u8,
        error_return_trace: ?*std.builtin.StackTrace,
    ) ![]const u8 {
        const io = std.Io.Threaded.global_single_threaded.io();
        const now_ts = std.Io.Timestamp.now(io, .real);
        const epoch_seconds = std.time.epoch.EpochSeconds{ .secs = @intCast(now_ts.toSeconds()) };
        const epoch_day = epoch_seconds.getEpochDay();
        const day_seconds = epoch_seconds.getDaySeconds();
        const year_day = epoch_day.calculateYearDay();
        const month_day = year_day.calculateMonthDay();

        const year = year_day.year;
        const month: u4 = @intFromEnum(month_day.month);
        const day = month_day.day_index + 1;
        const hour = day_seconds.getHoursIntoDay();
        const min = day_seconds.getMinutesIntoHour();
        const sec = day_seconds.getSecondsIntoMinute();

        var filename_buf: [64]u8 = undefined;
        const filename = std.fmt.bufPrint(
            &filename_buf,
            "crash_{d:0>4}{d:0>2}{d:0>2}_{d:0>2}{d:0>2}{d:0>2}.log",
            .{ year, month, day, hour, min, sec },
        ) catch filename_buf[0..9];

        const temp_dir = try getTempDir(allocator);
        defer allocator.free(temp_dir);

        const full_path = try std.fs.path.join(allocator, &.{ temp_dir, filename });
        errdefer allocator.free(full_path);

        const dir = std.Io.Dir.cwd();

        const file = dir.createFile(io, full_path, .{}) catch |primary_err| {
            const fallback_path = try std.fs.path.join(allocator, &.{ ".", filename });
            errdefer allocator.free(fallback_path);

            const fallback_file = dir.createFile(io, fallback_path, .{}) catch {
                allocator.free(full_path);
                return primary_err;
            };
            defer fallback_file.close(io);

            try writeCrashContent(fallback_file, message, error_return_trace, year, month, day, hour, min, sec);
            allocator.free(full_path);
            return fallback_path;
        };
        defer file.close(io);

        try writeCrashContent(file, message, error_return_trace, year, month, day, hour, min, sec);
        return full_path;
    }

    fn writeCrashContent(
        file: std.Io.File,
        message: []const u8,
        error_return_trace: ?*std.builtin.StackTrace,
        year: std.time.epoch.Year,
        month: u4,
        day: u5,
        hour: u5,
        min: u6,
        sec: u6,
    ) !void {
        const io = std.Io.Threaded.global_single_threaded.io();
        var buf: [4096]u8 = undefined;
        var writer = file.writer(io, &buf);

        try writer.interface.writeAll("========================================\n");
        try writer.interface.writeAll("           LIFT CRASH REPORT            \n");
        try writer.interface.writeAll("========================================\n\n");

        try writer.interface.print("Crash Time: {d:0>4}-{d:0>2}-{d:0>2} {d:0>2}:{d:0>2}:{d:0>2} UTC\n", .{
            year, month, day, hour, min, sec,
        });

        try writer.interface.print("Platform: {s}\n", .{@tagName(builtin.target.os.tag)});
        try writer.interface.print("Architecture: {s}\n", .{@tagName(builtin.target.cpu.arch)});
        try writer.interface.print("Zig Version: {s}\n\n", .{builtin.zig_version_string});

        try writer.interface.writeAll("Error Message:\n");
        try writer.interface.writeAll("--------------\n");
        try writer.interface.writeAll(message);
        try writer.interface.writeAll("\n\n");

        if (error_return_trace) |trace| {
            try writer.interface.writeAll("Stack Trace:\n");
            try writer.interface.writeAll("------------\n");

            var frame_index: usize = 0;
            var frames_left: usize = @min(trace.index, trace.instruction_addresses.len);

            while (frames_left > 0) : ({
                frames_left -= 1;
                frame_index += 1;
            }) {
                const return_address = trace.instruction_addresses[frames_left];
                try writer.interface.print("  [{d}] 0x{x:0>16}\n", .{ frame_index, return_address });
            }
        } else {
            try writer.interface.writeAll("No stack trace available\n");
        }

        try writer.interface.writeAll("\n========================================\n");
        try writer.interface.writeAll("End of crash report\n");
    }
};

test "getTempDir" {
    const allocator = std.testing.allocator;
    const temp_dir = try getTempDir(allocator);
    defer allocator.free(temp_dir);
    try std.testing.expect(temp_dir.len > 0);
}

test "CrashHandler.writeCrashLog creates file with expected content" {
    const allocator = std.testing.allocator;

    const test_message = "Test crash message for unit test";
    const log_path = try CrashHandler.writeCrashLog(allocator, test_message, null);
    defer {
        std.fs.cwd().deleteFile(log_path) catch {};
        allocator.free(log_path);
    }

    // Verify file exists
    const file = try std.fs.cwd().openFile(log_path, .{});
    defer file.close();

    // Verify content contains expected fields
    const content = try file.readToEndAlloc(allocator, 65536);
    defer allocator.free(content);

    try std.testing.expect(std.mem.containsAtLeast(u8, content, 1, "LIFT CRASH REPORT"));
    try std.testing.expect(std.mem.containsAtLeast(u8, content, 1, "Test crash message for unit test"));
    try std.testing.expect(std.mem.containsAtLeast(u8, content, 1, "Platform:"));
    try std.testing.expect(std.mem.containsAtLeast(u8, content, 1, "Architecture:"));
    try std.testing.expect(std.mem.containsAtLeast(u8, content, 1, "Zig Version:"));
    try std.testing.expect(std.mem.containsAtLeast(u8, content, 1, "No stack trace available"));
    try std.testing.expect(std.mem.containsAtLeast(u8, content, 1, "End of crash report"));
}
