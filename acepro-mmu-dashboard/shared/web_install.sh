#!/bin/bash

# =============================================================================
# KLIPPACE web-asset installation helpers (shared)
# =============================================================================
# Sourced by BOTH installer.sh (repo root) and acepro-mmu-dashboard/install.sh
# via `source_klippace_web_lib` / a direct `.` of this file.
#
# This exists in one place because the two callers had already drifted. The
# root installer linked only the standalone page and never patched index.html,
# so the MMU card itself — the main feature — was never installed by the
# installer most people run. The file list and the index.html injection are now
# defined once.
#
# The caller must provide these helpers (both installers already define them):
#   create_or_replace_symlink <source> <target> <description>
#   print_info / print_success / print_warning / print_error
# =============================================================================

# --- What gets installed -----------------------------------------------------

# The standalone ACE Dashboard page, reachable at http://<host>/ace.html, plus
# the assets ace.html loads itself. Verified against its markup: it references
# ace-dashboard.css, ace-dashboard-config.js, ace-dashboard.js,
# vue.global.prod.js and favicon.svg.
KLIPPACE_STANDALONE_FILES="ace.html ace-dashboard.js ace-dashboard.css ace-dashboard-config.js vue.global.prod.js favicon.svg"

# The injected MMU card. These two are inert on their own — patch_klippace_index_html
# is what makes the UI actually load them.
KLIPPACE_CARD_FILES="klippace-tool-mapper.js klippace-tool-mapper.css"

# Everything symlinked into the web root.
KLIPPACE_WEB_FILES="$KLIPPACE_STANDALONE_FILES $KLIPPACE_CARD_FILES"

# Marker used to decide whether index.html has already been patched.
KLIPPACE_INDEX_MARKER="klippace-tool-mapper.js"

# --- Functions ---------------------------------------------------------------

# Portable in-place sed: GNU sed takes `-i` bare, BSD/macOS sed requires `-i ''`.
# The GNU form is tried first and short-circuits on Linux; the BSD form is the
# fallback so the edit is never silently skipped on macOS.
_klippace_sed_inplace() {
    local expr="$1"
    local file="$2"
    sed -i "$expr" "$file" 2>/dev/null \
        || sed -i '' "$expr" "$file" 2>/dev/null \
        || true
}

# link_klippace_web_files <web_source_dir> <ui_dir> <ui_label>
#
# Symlinks every web asset into the UI's web root. Returns non-zero if any
# individual link failed, but keeps going so one declined replacement does not
# abandon the rest.
link_klippace_web_files() {
    local web_source_dir="$1"
    local ui_dir="$2"
    local ui_label="$3"
    local file
    local failed=0

    for file in $KLIPPACE_WEB_FILES; do
        create_or_replace_symlink "$web_source_dir/$file" "$ui_dir/$file" "$ui_label $file" || failed=1
    done

    return $failed
}

# patch_klippace_index_html <ui_dir> <ui_label>
#
# Adds the card's stylesheet and module script to the UI's index.html, which is
# what makes the card appear at all. Idempotent: re-running is a no-op.
# Returns non-zero if there is no index.html, or if the patch did not take, so
# callers can tell the user rather than leaving a silently unpatched UI.
patch_klippace_index_html() {
    local ui_dir="$1"
    local ui_label="$2"
    local index="$ui_dir/index.html"

    if [ ! -f "$index" ]; then
        print_warning "No index.html in $ui_dir — cannot add the card to $ui_label"
        return 1
    fi

    if grep -q "$KLIPPACE_INDEX_MARKER" "$index" 2>/dev/null; then
        print_info "$ui_label index.html already loads the card"
        return 0
    fi

    # GNU sed takes `-i` alone; BSD/macOS sed requires `-i ''`. The first form is
    # tried first and short-circuits on Linux; the second is a fallback so the
    # patch is not silently skipped on macOS.
    #
    # The closing tag is re-emitted WITH its two-space indent. Inserting a bare
    # `</head>` here would consume the original line's indentation, so
    # unpatch_klippace_index_html could not restore index.html byte-for-byte.
    # (A capture group like `\([[:space:]]*\)` would be more general, but
    # [[:space:]] matches newlines in sed and could eat the preceding line.)
    _klippace_sed_inplace 's|</head>|  <link rel="stylesheet" href="./klippace-tool-mapper.css">\n  </head>|' "$index"
    _klippace_sed_inplace 's|</body>|  <script type="module" src="./klippace-tool-mapper.js"></script>\n  </body>|' "$index"

    if grep -q "$KLIPPACE_INDEX_MARKER" "$index" 2>/dev/null; then
        print_success "Injected Tool Mapper into $ui_label index.html"
        # Stamp a cache-buster on the lines just added. Without this the URLs
        # would be bare, and a UI that caches by URL would keep serving the
        # first card it ever loaded.
        refresh_klippace_cache_buster "$ui_dir" "$ui_label" || true
        return 0
    fi

    print_warning "Could not patch $ui_label index.html automatically."
    print_info "Add these by hand:"
    print_info "  <link rel=\"stylesheet\" href=\"./klippace-tool-mapper.css\">   (in <head>)"
    print_info "  <script type=\"module\" src=\"./klippace-tool-mapper.js\"></script>   (before </body>)"
    return 1
}
# _klippace_hash
#
# Short content fingerprint of stdin, used as the card's cache-buster value.
# Ten characters is plenty to detect a change and keeps the URL readable.
# md5sum is GNU/Linux, md5 is macOS; cksum is the universal fallback.
_klippace_hash() {
    if command -v md5sum >/dev/null 2>&1; then
        md5sum | cut -c1-10
    elif command -v md5 >/dev/null 2>&1; then
        md5 -q | cut -c1-10
    else
        cksum | awk '{print $1}'
    fi
}

# _klippace_card_version <ui_dir>
#
# Fingerprints the card files *as served*, i.e. read through the UI directory so
# the symlinks resolve to whatever is actually live.
#
# Content, not mtime, on purpose: a `git checkout` rewrites mtime without
# changing a single byte, so an mtime-based buster would invalidate every
# client's cache on every pull that touches the repo for any reason.
_klippace_card_version() {
    local ui_dir="$1"
    local file
    for file in $KLIPPACE_CARD_FILES; do
        cat "$ui_dir/$file" 2>/dev/null
    done | _klippace_hash
}

# refresh_klippace_cache_buster <ui_dir> <ui_label>
#
# Re-stamps the ?v= query on the injected card lines so a browser picks up new
# card code without a manual hard-reload.
#
# WHY THIS IS NEEDED
#   index.html is the UI's own static file, so nothing regenerates those URLs.
#   The buster was previously a one-off epoch baked in when the card was first
#   injected, which meant it never changed again: after any card update the
#   browser kept serving its cached copy and the change appeared not to have
#   been deployed. Symptom: a fix that is provably live on disk (matching md5
#   over HTTP) but invisible in the UI.
#
# Idempotent: re-running with unchanged content is a no-op, so it is safe to
# call on every deploy rather than trying to detect whether the card changed.
# Returns 0 when there is nothing to do (not patched, or no index.html).
refresh_klippace_cache_buster() {
    local ui_dir="$1"
    local ui_label="$2"
    local index="$ui_dir/index.html"

    [ -f "$index" ] || return 0

    # Only touch an index.html that actually loads the card. If the card has not
    # been injected yet, patch_klippace_index_html will stamp it.
    if ! grep -q "$KLIPPACE_INDEX_MARKER" "$index" 2>/dev/null; then
        return 0
    fi

    local ver
    ver="$(_klippace_card_version "$ui_dir")"
    if [ -z "$ver" ]; then
        print_warning "Could not fingerprint the card for $ui_label — cache-buster left alone"
        return 1
    fi

    # Already current? Then leave the file untouched. Avoids rewriting the UI's
    # index.html (and its mtime) on every single deploy.
    if grep -q "klippace-tool-mapper\.js?v=${ver}" "$index" 2>/dev/null; then
        return 0
    fi

    local file
    for file in $KLIPPACE_CARD_FILES; do
        # Strip any existing query first, then append the current one. Done as
        # two plain BRE substitutions rather than one optional-group pattern,
        # because `\?` on a group is a GNU/BSD extension and this runs under
        # whatever sed the host provides.
        #
        # The `.` before the filename is escaped so foo-klippace-tool-mapper.js
        # could never match, and the line is selected by the filename alone so a
        # path prefix (./ or ./assets/) is irrelevant.
        _klippace_sed_inplace "/klippace-tool-mapper\.${file##*.}/ s|\(klippace-tool-mapper\.${file##*.}\)?v=[^\"']*|\1|" "$index"
        _klippace_sed_inplace "/klippace-tool-mapper\.${file##*.}/ s|\(klippace-tool-mapper\.${file##*.}\)|\1?v=${ver}|" "$index"
    done

    if grep -q "klippace-tool-mapper\.js?v=${ver}" "$index" 2>/dev/null; then
        print_success "Card cache-buster for $ui_label refreshed (${ver})"
        return 0
    fi

    print_warning "Could not refresh the card cache-buster in $ui_label index.html"
    print_info "A browser hard-reload will still pick up card changes."
    return 1
}
# --- Uninstall counterparts --------------------------------------------------

# unlink_klippace_web_files <ui_dir>
#
# Removes exactly what link_klippace_web_files installs. Kept beside the install
# list so an uninstall cannot miss a file the installer added. That is precisely
# what had happened: the uninstaller still used the original five-file list and
# left klippace-tool-mapper.{js,css} and vue.global.prod.js behind, so the card
# kept working after "uninstalling" it.
unlink_klippace_web_files() {
    local ui_dir="$1"
    local file
    local target
    for file in $KLIPPACE_WEB_FILES; do
        target="$ui_dir/$file"
        if [ -L "$target" ] || [ -e "$target" ]; then
            rm -f "$target"
            print_success "Removed: $target"
        fi
    done
}

# unpatch_klippace_index_html <ui_dir> <ui_label>
#
# Removes the card's <link>/<script> lines from index.html, so uninstalling does
# not leave the UI referencing files that no longer exist.
unpatch_klippace_index_html() {
    local ui_dir="$1"
    local ui_label="$2"
    local index="$ui_dir/index.html"

    if [ ! -f "$index" ]; then
        return 0
    fi
    if ! grep -q "$KLIPPACE_INDEX_MARKER" "$index" 2>/dev/null; then
        return 0
    fi

    _klippace_sed_inplace '/klippace-tool-mapper\.css/d' "$index"
    _klippace_sed_inplace '/klippace-tool-mapper\.js/d' "$index"

    if grep -q "$KLIPPACE_INDEX_MARKER" "$index" 2>/dev/null; then
        print_warning "Could not remove the card reference from $ui_label index.html"
        print_info "Remove the klippace-tool-mapper lines from $index by hand."
        return 1
    fi
    print_success "Removed the card reference from $ui_label index.html"
    return 0
}
