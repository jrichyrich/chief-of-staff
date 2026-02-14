// imessage-reader.c — Read iMessage database and output JSON
//
// Build: cc -O2 -o scripts/imessage-reader scripts/imessage-reader.c -lsqlite3
// Sign:  codesign --force --sign - --identifier "com.chiefofstaff.imessage-reader" scripts/imessage-reader
//
// Usage: imessage-reader [--minutes N]
//   Reads messages from ~/Library/Messages/chat.db where text starts
//   with 'jarvis:'. Default lookback is 20 minutes.
//   Outputs JSON array to stdout.
//
// Note: When sending iMessage to yourself, macOS stores the text on the
// is_from_me=0 row and leaves is_from_me=1 empty. We match on text
// prefix only and deduplicate by text+timestamp to handle this.

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sqlite3.h>
#include <pwd.h>
#include <unistd.h>

#define DEFAULT_MINUTES 20
#define MAX_PATH 1024

static const char *SQL_QUERY =
    "SELECT "
    "    m.guid, "
    "    m.text, "
    "    datetime(m.date / 1000000000 + 978307200, 'unixepoch', 'localtime') AS date_local "
    "FROM message m "
    "WHERE "
    "    m.text LIKE 'jarvis:%' "
    "    AND m.date > ((strftime('%s', 'now') - 978307200 - (? * 60)) * 1000000000) "
    "GROUP BY m.text, date_local "
    "ORDER BY m.date DESC "
    "LIMIT 50;";

static void print_json_string(const char *s) {
    putchar('"');
    if (s == NULL) {
        putchar('"');
        return;
    }
    for (const char *p = s; *p; p++) {
        unsigned char c = (unsigned char)*p;
        switch (c) {
        case '"':  fputs("\\\"", stdout); break;
        case '\\': fputs("\\\\", stdout); break;
        case '\n': fputs("\\n", stdout);  break;
        case '\r': fputs("\\r", stdout);  break;
        case '\t': fputs("\\t", stdout);  break;
        case '\b': fputs("\\b", stdout);  break;
        case '\f': fputs("\\f", stdout);  break;
        default:
            if (c < 0x20) {
                printf("\\u%04x", c);
            } else {
                putchar(c);
            }
            break;
        }
    }
    putchar('"');
}

static void usage(const char *prog) {
    fprintf(stderr, "Usage: %s [--minutes N]\n", prog);
    exit(1);
}

int main(int argc, char *argv[]) {
    int minutes = DEFAULT_MINUTES;

    /* Parse arguments */
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--minutes") == 0) {
            if (i + 1 >= argc) {
                fprintf(stderr, "Error: --minutes requires a value\n");
                usage(argv[0]);
            }
            minutes = atoi(argv[++i]);
            if (minutes <= 0) {
                fprintf(stderr, "Error: minutes must be a positive integer\n");
                return 1;
            }
        } else {
            fprintf(stderr, "Error: unknown argument '%s'\n", argv[i]);
            usage(argv[0]);
        }
    }

    /* Build path to chat.db */
    char db_path[MAX_PATH];
    const char *home = getenv("HOME");
    if (!home) {
        struct passwd *pw = getpwuid(getuid());
        if (pw) {
            home = pw->pw_dir;
        } else {
            fprintf(stderr, "Error: cannot determine home directory\n");
            return 1;
        }
    }
    snprintf(db_path, sizeof(db_path), "%s/Library/Messages/chat.db", home);

    /* Open database read-only */
    sqlite3 *db = NULL;
    int rc = sqlite3_open_v2(db_path, &db, SQLITE_OPEN_READONLY, NULL);
    if (rc != SQLITE_OK) {
        fprintf(stderr, "Error: cannot open %s: %s\n", db_path, sqlite3_errmsg(db));
        sqlite3_close(db);
        return 1;
    }

    /* Prepare statement */
    sqlite3_stmt *stmt = NULL;
    rc = sqlite3_prepare_v2(db, SQL_QUERY, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        fprintf(stderr, "Error: SQL prepare failed: %s\n", sqlite3_errmsg(db));
        sqlite3_close(db);
        return 1;
    }

    /* Bind minutes parameter */
    rc = sqlite3_bind_int(stmt, 1, minutes);
    if (rc != SQLITE_OK) {
        fprintf(stderr, "Error: bind failed: %s\n", sqlite3_errmsg(db));
        sqlite3_finalize(stmt);
        sqlite3_close(db);
        return 1;
    }

    /* Execute and output JSON */
    printf("[");
    int row_count = 0;
    while ((rc = sqlite3_step(stmt)) == SQLITE_ROW) {
        if (row_count > 0) {
            printf(",");
        }
        const char *guid       = (const char *)sqlite3_column_text(stmt, 0);
        const char *text       = (const char *)sqlite3_column_text(stmt, 1);
        const char *date_local = (const char *)sqlite3_column_text(stmt, 2);

        printf("{\"guid\":");
        print_json_string(guid);
        printf(",\"text\":");
        print_json_string(text);
        printf(",\"date_local\":");
        print_json_string(date_local);
        printf("}");
        row_count++;
    }
    printf("]\n");

    if (rc != SQLITE_DONE) {
        fprintf(stderr, "Error: query execution failed: %s\n", sqlite3_errmsg(db));
        sqlite3_finalize(stmt);
        sqlite3_close(db);
        return 1;
    }

    sqlite3_finalize(stmt);
    sqlite3_close(db);
    return 0;
}
