import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Button, Card, Modal, Space, Tag, Tooltip, Typography, message } from "antd";
import { createDomain, createCredential, deleteCredential, fetchCredentials, WorkerRedisAclInfo } from "../api/admin";
import { createMyCredential, deleteMyCredential, fetchMyCredentials } from "../api/domain";
import { createJob, fetchTemplates } from "../api/jobs";
import { withTempToken, getActiveDomain, setActiveDomain } from "../api/client";

const { Text, Paragraph } = Typography;

interface Props {
  isAdmin: boolean;
}

/** Demo/test admin quick-actions — only rendered when demo mode is on (see
 * useDemoMode / scheduler HYDRA_DEMO_MODE). Every action here composes
 * existing, already-authorized endpoints; nothing here is a new capability,
 * just a one-click shortcut around ones that already exist. */
export function DemoQuickActions({ isAdmin }: Props) {
  const queryClient = useQueryClient();
  const [creatingDomain, setCreatingDomain] = useState(false);
  const [domainResult, setDomainResult] = useState<{ domain: string; token: string; acl?: WorkerRedisAclInfo } | null>(null);
  const [checkingCred, setCheckingCred] = useState(false);
  const [credResult, setCredResult] = useState<{ ok: boolean; detail: string } | null>(null);

  const handleCreateDemoDomain = async () => {
    setCreatingDomain(true);
    try {
      const suffix = Math.random().toString(16).slice(2, 8);
      const domain = `demo-${suffix}`;
      const created = await createDomain({ domain, display_name: `Demo domain (${suffix})` });
      const token = created.token as unknown as string;
      const acl = (created as any).worker_redis_acl as WorkerRedisAclInfo | undefined;

      const templates = await fetchTemplates();
      const demoJobs = (templates ?? []).filter((t: any) => typeof t.name === "string" && t.name.startsWith("demo-"));

      // createJob() sends whatever domain+token are "active" — the new
      // domain isn't active yet, so switch to it (and swap in its fresh
      // token) just for the seeding calls, then restore both.
      const previousActiveDomain = getActiveDomain();
      setActiveDomain(domain);
      let seeded = 0;
      try {
        const results = await withTempToken(token, () =>
          Promise.allSettled(demoJobs.map((t: any) => {
            const { id: _id, ...payload } = t;
            return createJob(payload as any);
          })),
        );
        seeded = results.filter((r) => r.status === "fulfilled").length;
      } finally {
        setActiveDomain(previousActiveDomain);
      }

      setDomainResult({ domain, token, acl });
      message.success(`Created domain '${domain}' and seeded ${seeded}/${demoJobs.length} demo job(s)`);
      queryClient.invalidateQueries({ queryKey: ["domains"] });
    } catch (err) {
      message.error((err as Error).message);
    } finally {
      setCreatingDomain(false);
    }
  };

  const handleCredentialRoundTrip = async () => {
    setCheckingCred(true);
    setCredResult(null);
    const name = `demo-roundtrip-${Math.random().toString(16).slice(2, 8)}`;
    const create = isAdmin ? (p: any) => createCredential(p) : createMyCredential;
    const del = isAdmin ? (n: string) => deleteCredential(n) : deleteMyCredential;
    const list = isAdmin ? () => fetchCredentials() : fetchMyCredentials;
    try {
      await create({ name, credential_type: "generic", extra: { note: "acceptance round-trip check" } });

      const { credentials } = await list();
      const match: any = credentials.find((c: any) => c.name === name);
      const serialized = JSON.stringify(match ?? {});
      const secretLeaked = serialized.includes("acceptance round-trip check");

      await del(name);

      if (match && !secretLeaked) {
        setCredResult({ ok: true, detail: "Created, listed without the secret payload, and deleted successfully." });
      } else if (!match) {
        setCredResult({ ok: false, detail: "Credential did not appear in the list after creation." });
      } else {
        setCredResult({ ok: false, detail: "Secret payload was present in the list response — this should never happen." });
      }
    } catch (err) {
      setCredResult({ ok: false, detail: (err as Error).message });
    } finally {
      setCheckingCred(false);
    }
  };

  return (
    <Card title="Demo Quick Actions" size="small">
      <Space direction="vertical" size={16} style={{ width: "100%" }}>
        <div>
          <Space align="center">
            <Tooltip title={isAdmin ? "" : "Requires an admin token"}>
              <Button onClick={handleCreateDemoDomain} loading={creatingDomain} disabled={!isAdmin}>
                Create Demo Domain
              </Button>
            </Tooltip>
            <Text type="secondary" style={{ fontSize: 12 }}>
              Provisions a throwaway domain and seeds it with the demo-* example jobs.
            </Text>
          </Space>
        </div>
        <div>
          <Space align="center">
            <Button onClick={handleCredentialRoundTrip} loading={checkingCred}>
              Credential Round-Trip Check
            </Button>
            <Text type="secondary" style={{ fontSize: 12 }}>
              Creates, verifies masking on, and deletes a throwaway credential in the active domain.
            </Text>
          </Space>
          {credResult && (
            <div style={{ marginTop: 8 }}>
              <Tag color={credResult.ok ? "success" : "error"}>{credResult.ok ? "PASS" : "FAIL"}</Tag>
              <Text type="secondary">{credResult.detail}</Text>
            </div>
          )}
        </div>
      </Space>

      <Modal
        open={Boolean(domainResult)}
        onCancel={() => setDomainResult(null)}
        footer={<Button onClick={() => setDomainResult(null)}>Close</Button>}
        title={`Demo domain created: ${domainResult?.domain ?? ""}`}
      >
        <Paragraph>
          <Text strong>Domain token:</Text> <Text code copyable>{domainResult?.token}</Text>
        </Paragraph>
        {domainResult?.acl && (
          <Paragraph>
            <Text strong>Worker Redis ACL password:</Text> <Text code copyable>{domainResult.acl.password}</Text>
          </Paragraph>
        )}
        <Paragraph type="secondary">
          Switch to this domain (Settings → Domain) using the token above to see the seeded jobs, or start a worker
          against it to actually run them.
        </Paragraph>
      </Modal>
    </Card>
  );
}
