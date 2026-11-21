// Qualification-only tests. Append unchanged to both test builds.
#if defined(_WIN32)
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <psapi.h>
#else
#include <link.h>
#endif
#include <algorithm>
#include <cmath>
#include <cstdio>

namespace opencv_test
{
namespace
{
TEST(Mission19_Diagnostics, LoadedModules)
{
    const std::vector<cv::Point3f> points = {{0,0,0}, {1,2,3}};
    cv::Vec6f line;
    cv::fitLine(points, line, cv::DIST_L2, 0, 0, 0);
#if defined(_WIN32)
    HMODULE modules[256];
    DWORD bytes = 0;
    ASSERT_TRUE(K32EnumProcessModules(GetCurrentProcess(), modules, sizeof(modules), &bytes));
    ASSERT_LE(static_cast<size_t>(bytes), sizeof(modules));
    for (size_t i = 0; i < bytes / sizeof(HMODULE); ++i)
    {
        char path[4096];
        const DWORD size = GetModuleFileNameA(modules[i], path, sizeof(path));
        if (size && size < sizeof(path))
            std::printf("M19_MODULE %s\n", path);
    }
#else
    dl_iterate_phdr([](dl_phdr_info* info, size_t, void*) {
        if (info->dlpi_name && *info->dlpi_name)
            std::printf("M19_MODULE %s\n", info->dlpi_name);
        return 0;
    }, nullptr);
#endif
    std::printf("%s\n", cv::getBuildInformation().c_str());
}

static void checkDirection(const std::vector<cv::Point3f>& points, const cv::Vec3d& expected)
{
    cv::Vec6f line;
    cv::fitLine(points, line, cv::DIST_L2, 0, 0, 0);
    const cv::Vec3d direction(line[0], line[1], line[2]);
    EXPECT_NEAR(1.0, cv::norm(direction), 1e-6);
    EXPECT_LT(cv::norm(direction.cross(expected)) / cv::norm(expected), 1e-6);
    for (int i = 3; i < 6; ++i)
        EXPECT_TRUE(std::isfinite(line[i]));
}

TEST(Mission19_Controls, ExtremeScales)
{
    for (int power : {-145, -75, 80, 120})
    {
        SCOPED_TRACE(power);
        std::vector<cv::Point3f> points;
        for (int i = -2; i <= 2; ++i)
        {
            const float t = std::ldexp(static_cast<float>(i), power);
            points.emplace_back(t, 2*t, 3*t);
        }
        checkDirection(points, cv::Vec3d(1,2,3));
    }
}

TEST(Mission19_Controls, BlockBoundariesAndReversal)
{
    const cv::Point3f origin(1000000, -2000000, 1000000);
    const cv::Point3f step(3,5,7);
    for (int count : {255,256,257,511,512,513})
    {
        SCOPED_TRACE(count);
        std::vector<cv::Point3f> points(count, origin);
        for (int i = count / 2; i < count; ++i)
            points[i] = origin + step;
        points.back() = origin + step * 2.0f;
        checkDirection(points, cv::Vec3d(3,5,7));
        std::reverse(points.begin(), points.end());
        checkDirection(points, cv::Vec3d(3,5,7));
    }
}

TEST(Mission19_Controls, TiedObjective)
{
    const std::vector<cv::Point3f> points = {{-1,0,0}, {1,0,0}, {0,-1,0},
                                              {0,1,0}, {0,0,-1}, {0,0,1}};
    cv::Vec6f line;
    cv::fitLine(points, line, cv::DIST_L2, 0, 0, 0);
    const cv::Vec3d direction(line[0], line[1], line[2]);
    const cv::Vec3d anchor(line[3], line[4], line[5]);
    const double length = cv::norm(direction);
    ASSERT_NEAR(1.0, length, 1e-6);
    double squaredError = 0;
    for (const auto& point : points)
    {
        const auto cross = (cv::Vec3d(point.x, point.y, point.z)-anchor).cross(direction/length);
        squaredError += cross.dot(cross);
    }
    EXPECT_NEAR(2.0/3.0, squaredError/points.size(), 1e-6);
}
}
} // namespace opencv_test
