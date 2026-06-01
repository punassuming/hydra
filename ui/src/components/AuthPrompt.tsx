import { useEffect, useState } from "react";
import { Input, message } from "antd";
import { setTokenForDomain, setTokenPreference, validateAdminToken, validateDomainToken } from "../api/client";
import { useActiveDomain } from "../context/ActiveDomainContext";
import { HydraLogo } from "./HydraLogo";
import { useTheme } from "../theme";

interface Props {
  open: boolean;
  onClose: () => void;
  onSuccess?: () => void;
}

export function AuthPrompt({ onSuccess }: Props) {
  const [token, setToken] = useState("");
  const [adminToken, setAdminToken] = useState("");
  const [domainInput, setDomainInput] = useState("prod");
  const [loading, setLoading] = useState(false);
  const { domain, setDomain } = useActiveDomain();
  const { isDarkMode, colors } = useTheme();

  useEffect(() => {
    setDomainInput(domain || "prod");
    setToken("");
    setAdminToken("");
  }, [domain]);

  const handleConnect = async () => {
    const finalToken = token.trim();
    const finalDomain = domainInput.trim();
    if (!finalDomain) {
      message.error("Domain required");
      return;
    }
    if (!finalToken) {
      message.error("Domain token required");
      return;
    }
    setLoading(true);
    try {
      await validateDomainToken(finalDomain, finalToken);
      setTokenForDomain(finalDomain, finalToken);
      setTokenPreference("domain");
      setDomain(finalDomain);

      const adminTrim = adminToken.trim();
      if (adminTrim) {
        try {
          await validateAdminToken(adminTrim);
          setTokenForDomain("admin", adminTrim);
        } catch {
          message.warning("Admin token could not be validated — domain connected without admin access");
        }
      }

      message.success(`Connected to domain ${finalDomain}`);
      onSuccess?.();
    } catch (err) {
      message.error(err instanceof Error ? err.message : "Authentication failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-wrap">
      <div className="auth-card">
        <div className="auth-logo-row">
          <HydraLogo size={36} color={colors.primary} />
          <div>
            <p className="auth-title">Hydra Scheduler</p>
            <p className="auth-subtitle">Connect to a domain to continue</p>
          </div>
        </div>

        <div className="auth-field">
          <label className="auth-field-label">Domain *</label>
          <Input
            value={domainInput}
            onChange={(e) => setDomainInput(e.target.value)}
            placeholder="prod"
            onPressEnter={handleConnect}
            style={{ fontFamily: "var(--font-mono)" }}
          />
        </div>

        <div className="auth-field">
          <label className="auth-field-label">Domain Token *</label>
          <Input.Password
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder="hydra_dom_…"
            onPressEnter={handleConnect}
            style={{ fontFamily: "var(--font-mono)" }}
          />
          <div style={{ fontSize: 11, color: "var(--v2-text-3)", marginTop: 4 }}>
            Used for both UI access and worker connection.
          </div>
        </div>

        <div className="auth-field">
          <label className="auth-field-label">
            Admin Token <span style={{ color: "var(--v2-text-3)" }}>(optional)</span>
          </label>
          <Input.Password
            value={adminToken}
            onChange={(e) => setAdminToken(e.target.value)}
            placeholder="Leave blank to skip admin access"
            onPressEnter={handleConnect}
            style={{ fontFamily: "var(--font-mono)" }}
          />
        </div>

        <div style={{ marginTop: 16 }}>
          <button
            onClick={handleConnect}
            disabled={loading}
            style={{
              width: "100%",
              height: 36,
              background: colors.primary,
              color: isDarkMode ? "#0c1220" : "#ffffff",
              border: "none",
              borderRadius: "var(--radius-sm)",
              fontFamily: "var(--font-sans)",
              fontWeight: 600,
              fontSize: 14,
              cursor: loading ? "not-allowed" : "pointer",
              opacity: loading ? 0.7 : 1,
              transition: "opacity 180ms ease",
            }}
          >
            {loading ? "Connecting…" : "Connect"}
          </button>
        </div>

        <div className="auth-divider" />

        <div className="auth-footer">
          Workers authenticate with the same <code>domain + token</code> pair.
        </div>
      </div>
    </div>
  );
}
