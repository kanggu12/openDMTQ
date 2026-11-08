// Time zones as the guest's C library reads them: from the file where Android 6.0 kept them, which the runtime finds
// wherever the host keeps them (a phone's time zone module, the desktop's sysroot), and the zone from TZ or else from
// the persist.sys.timezone property, as on a phone. Fixed instants in zones whose rules held for years, and in one whose
// rules changed (Sao Paulo has had no daylight saving time since 2019): a file from before then gets that one wrong.
// Prints one line per check.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/system_properties.h>
#include <time.h>

static int failures = 0;
#define CHECK(name, cond) do { int ok_ = (cond); printf("%s %s\n", ok_ ? "ok  " : "FAIL", name); if (!ok_) failures++; } while (0)

// 2026-01-15 and 2026-07-15, 00:00 UTC: a winter and a summer in the north.
static const time_t kWinter = 1768435200, kSummer = 1784073600;

// The local time at `when` in the zone TZ names now.
static struct tm local_at(time_t when) {
    struct tm tm;
    tzset();
    localtime_r(&when, &tm);
    return tm;
}

// `zone`'s offset from UTC and abbreviation at `when`.
static void offset_at(const char* zone, time_t when, long want, const char* abbr) {
    setenv("TZ", zone, 1);
    struct tm tm = local_at(when);
    char name[160];
    snprintf(name, sizeof name, "%s at %ld: %+ld %s (want %+ld %s)", zone, (long)when, tm.tm_gmtoff,
             tm.tm_zone ? tm.tm_zone : "(none)", want, abbr);
    CHECK(name, tm.tm_gmtoff == want && tm.tm_zone && strcmp(tm.tm_zone, abbr) == 0);
}

int main(void) {
    setvbuf(stdout, NULL, _IONBF, 0);

    offset_at("Asia/Seoul", kWinter, 9 * 3600, "KST");
    offset_at("Asia/Seoul", kSummer, 9 * 3600, "KST");
    offset_at("Europe/Berlin", kWinter, 3600, "CET");
    offset_at("Europe/Berlin", kSummer, 2 * 3600, "CEST");
    offset_at("America/New_York", kWinter, -5 * 3600, "EST");
    offset_at("America/New_York", kSummer, -4 * 3600, "EDT");
    // In a southern summer, when Sao Paulo had daylight saving time until 2019.
    offset_at("America/Sao_Paulo", kWinter, -3 * 3600, "-03");
    // An old name, which the file keeps as a link to the current zone.
    offset_at("Asia/Calcutta", kWinter, 5 * 3600 + 1800, "IST");

    // With no TZ, the zone the property names: the phone's own, or the desktop host's.
    char zone[PROP_VALUE_MAX] = "";
    __system_property_get("persist.sys.timezone", zone);
    char name[160];
    snprintf(name, sizeof name, "persist.sys.timezone names a zone (\"%s\")", zone);
    CHECK(name, zone[0] != 0);
    setenv("TZ", zone, 1);
    struct tm named = local_at(kSummer);
    unsetenv("TZ");
    struct tm unset = local_at(kSummer);
    snprintf(name, sizeof name, "no TZ: the property's zone, %+ld %s (want %+ld %s)", unset.tm_gmtoff,
             unset.tm_zone ? unset.tm_zone : "(none)", named.tm_gmtoff, named.tm_zone ? named.tm_zone : "(none)");
    CHECK(name, unset.tm_gmtoff == named.tm_gmtoff && unset.tm_zone && named.tm_zone && strcmp(unset.tm_zone, named.tm_zone) == 0);

    if (failures == 0) printf("ALL CHECKS PASSED\n");
    return failures == 0 ? 0 : 1;
}
