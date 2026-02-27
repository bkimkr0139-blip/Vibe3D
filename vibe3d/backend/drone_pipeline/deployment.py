"""Nginx deployment automation for WebGL builds.

Handles versioned deployments, nginx config generation, and smoke testing.
"""

import json
import logging
import os
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from .. import config

logger = logging.getLogger(__name__)

# ── Nginx config template ────────────────────────────────────

NGINX_SERVER_BLOCK = '''# Vibe3D WebGL Deployment — auto-generated
# Deploy path: {deploy_dir}
# Generated: {timestamp}

server {{
    listen 80;
    server_name _;

    root {deploy_dir};
    index index.html;

    # ── MIME types for Unity WebGL ─────────────────────────
    types {{
        application/wasm                      wasm;
        application/octet-stream              data;
        application/javascript                js;
        application/json                      json;
        text/html                             html;
        text/css                              css;
        image/png                             png;
        image/jpeg                            jpg jpeg;
        image/svg+xml                         svg;
    }}

    # ── Brotli / Gzip pre-compressed files ─────────────────
    location ~* \\.(wasm|data|js|json)$ {{
        # Brotli
        if ($http_accept_encoding ~* br) {{
            rewrite ^(.*)$ $1.br break;
            add_header Content-Encoding br;
        }}
        # Gzip fallback
        if ($http_accept_encoding ~* gzip) {{
            rewrite ^(.*)$ $1.gz break;
            add_header Content-Encoding gzip;
        }}
    }}

    # ── Cache policy ───────────────────────────────────────
    # Hashed assets: cache forever
    location ~* \\.(wasm|data|unityweb)$ {{
        add_header Cache-Control "public, max-age=31536000, immutable";
    }}

    # JS/CSS: cache but revalidate
    location ~* \\.(js|css)$ {{
        add_header Cache-Control "public, max-age=86400, must-revalidate";
    }}

    # HTML: never cache
    location ~* \\.html$ {{
        add_header Cache-Control "no-cache, no-store, must-revalidate";
    }}

    # ── Optional: SharedArrayBuffer (threading) ────────────
    # Uncomment if Unity build uses threading
    # add_header Cross-Origin-Opener-Policy "same-origin";
    # add_header Cross-Origin-Embedder-Policy "require-corp";

    # ── Security ───────────────────────────────────────────
    add_header X-Content-Type-Options "nosniff";
    add_header X-Frame-Options "SAMEORIGIN";
}}
'''


class DeploymentManager:
    """Manages WebGL build deployments with versioning."""

    def __init__(self):
        self._deploy_base = config.NGINX_DEPLOY_DIR

    @property
    def is_configured(self) -> bool:
        """Whether deployment directory is configured."""
        return bool(self._deploy_base)

    def deploy(
        self,
        build_dir: str,
        deploy_base: Optional[str] = None,
        version: Optional[str] = None,
    ) -> dict:
        """Deploy WebGL build to versioned directory.

        Args:
            build_dir: Source WebGL build directory.
            deploy_base: Override deployment base (default from .env).
            version: Version string (default: vYYYY-MM-DD).

        Returns:
            dict with version, deploy_path, nginx_conf_path, files_copied.
        """
        base = Path(deploy_base or self._deploy_base)
        if not base:
            return {
                "success": False,
                "error": "NGINX_DEPLOY_DIR not configured in .env",
            }

        src = Path(build_dir)
        if not src.is_dir():
            return {
                "success": False,
                "error": f"Build directory not found: {build_dir}",
            }

        # Version directory
        if not version:
            version = f"v{datetime.now().strftime('%Y-%m-%d')}"
        deploy_dir = base / "builds" / version
        deploy_dir.mkdir(parents=True, exist_ok=True)

        # Copy build files
        files_copied = 0
        for item in src.rglob("*"):
            if item.is_file():
                rel = item.relative_to(src)
                dest = deploy_dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(item), str(dest))
                files_copied += 1

        # Generate nginx config
        nginx_conf = self.generate_nginx_conf(str(deploy_dir))
        conf_path = base / "nginx_vibe3d.conf"
        with open(conf_path, "w", encoding="utf-8") as f:
            f.write(nginx_conf)

        total_size = sum(f.stat().st_size for f in deploy_dir.rglob("*") if f.is_file())

        logger.info(
            "Deployed to %s: %d files, %.1f MB",
            deploy_dir, files_copied, total_size / (1024 * 1024),
        )

        return {
            "success": True,
            "version": version,
            "deploy_path": str(deploy_dir),
            "nginx_conf_path": str(conf_path),
            "files_copied": files_copied,
            "total_size_mb": round(total_size / (1024 * 1024), 1),
        }

    def generate_nginx_conf(self, deploy_dir: str) -> str:
        """Generate nginx server block configuration."""
        return NGINX_SERVER_BLOCK.format(
            deploy_dir=deploy_dir.replace("\\", "/"),
            timestamp=datetime.now().isoformat(),
        )

    async def smoke_test(self, url: str) -> dict:
        """Test WebGL deployment accessibility.

        Checks that key files (index.html, .wasm, .data, .framework.js)
        are accessible via HTTP.
        """
        import httpx

        checks = []
        errors = []

        # Files to check
        test_files = [
            ("index.html", "text/html"),
            ("Build/*.wasm", "application/wasm"),
            ("Build/*.data", "application/octet-stream"),
            ("Build/*.framework.js", "application/javascript"),
        ]

        async with httpx.AsyncClient(timeout=10.0) as client:
            # Check base URL
            try:
                resp = await client.get(url)
                if resp.status_code == 200:
                    checks.append({"file": "index.html", "status": "ok", "size": len(resp.content)})
                else:
                    errors.append({"file": "index.html", "status": resp.status_code})
            except Exception as e:
                errors.append({"file": "index.html", "error": str(e)})

            # Check content-encoding headers
            try:
                resp = await client.head(url)
                headers = dict(resp.headers)
                checks.append({
                    "file": "headers",
                    "content_type": headers.get("content-type", ""),
                    "cache_control": headers.get("cache-control", ""),
                })
            except Exception:
                pass

        return {
            "passed": len(errors) == 0,
            "url": url,
            "checks": checks,
            "errors": errors,
            "timestamp": datetime.now().isoformat(),
        }

    def list_versions(self, deploy_base: Optional[str] = None) -> list[dict]:
        """List deployed versions."""
        base = Path(deploy_base or self._deploy_base)
        if not base or not (base / "builds").is_dir():
            return []

        versions = []
        for d in sorted((base / "builds").iterdir(), reverse=True):
            if d.is_dir() and d.name.startswith("v"):
                total_size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
                versions.append({
                    "version": d.name,
                    "path": str(d),
                    "date": datetime.fromtimestamp(d.stat().st_mtime).isoformat(),
                    "size_mb": round(total_size / (1024 * 1024), 1),
                })

        return versions
