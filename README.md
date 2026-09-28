# Turkish + Dutch IPTV builder

This setup builds one standard M3U from the current public IPTV Nexus country datasets for:
- Netherlands (`nl`)
- Türkiye (`tr`)

The upstream project publishes per-country playlists and API shards and reports stream-health data. This builder selects one best currently-online stream per channel, writes a clean UTF-8 M3U, and optionally runs `ffprobe` against every selected stream.

## Local Windows run

Install Python 3 and FFmpeg, then:

```powershell
python build_turk_nl.py --probe --workers 12
```

Output:
- `turks_nederland_verified.m3u`
- `turks_nederland_validation.txt`

## GitHub Actions

1. Upload `build_turk_nl.py` to the root of your `SGCC96/iptv` repository.
2. Upload `.github/workflows/update-playlist.yml`.
3. In GitHub: Actions → “Update Turkish + Dutch IPTV” → Run workflow.
4. The action also runs every 6 hours.

Once GitHub Pages is enabled for the repo, the generated M3U will be available at:

`https://sgcc96.github.io/iptv/turks_nederland_verified.m3u`

This is a live generated list, so it is preferable to claiming that one static file can contain “literally every channel that exists” forever.

Only publicly accessible streams returned by the upstream dataset are used. This does not create access to paid channels requiring credentials or bypass geo/DRM protections.
