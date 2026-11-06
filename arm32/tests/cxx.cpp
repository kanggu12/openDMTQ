// C++ runtime in the guest: exceptions across frames (ARM EHABI unwinding through the linker's
// dl_unwind_find_exidx), RTTI, std::thread, std::mutex and iostreams.
#include <atomic>
#include <cstdio>
#include <iostream>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <typeinfo>
#include <vector>

static int failures = 0;
static void check(const char* name, bool ok) {
    std::printf("%s %s\n", ok ? "ok  " : "FAIL", name);
    if (!ok) failures++;
}

struct Base { virtual ~Base() = default; };
struct Derived : Base { int v = 42; };

[[gnu::noinline]] static int thrower(int depth) {
    if (depth == 0) throw std::runtime_error("deep");
    return thrower(depth - 1) + 1;
}

int main() {
    bool caught = false;
    try {
        thrower(20);
    } catch (const std::exception& e) {
        caught = std::string(e.what()) == "deep";
    }
    check("exception through 20 frames", caught);
    Base* b = new Derived;
    check("dynamic_cast and typeid", dynamic_cast<Derived*>(b) && dynamic_cast<Derived*>(b)->v == 42 && typeid(*b) == typeid(Derived));
    delete b;
    std::atomic<int> total{0};
    std::mutex mx;
    std::vector<std::thread> ts;
    std::vector<int> seen;
    for (int i = 0; i < 8; i++) {
        ts.emplace_back([&, i] {
            try {
                if (i % 2) throw i;
            } catch (int v) {
                total += v;
            }
            std::lock_guard<std::mutex> g(mx);
            seen.push_back(i);
        });
    }
    for (auto& t : ts) t.join();
    check("8 std::threads throwing and catching", total == 1 + 3 + 5 + 7 && seen.size() == 8);
    std::ostringstream os;
    os << "pi=" << 3.25 << " n=" << 12;
    check("iostreams", os.str() == "pi=3.25 n=12");
    std::cout << (failures ? "SOME CHECKS FAILED" : "ALL CHECKS PASSED") << std::endl;
    return failures ? 1 : 7;
}
