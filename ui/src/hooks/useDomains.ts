import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchDomains } from "../api/admin";

type DomainOption = { domain: string; label: string };

export function useDomains() {
  const [options, setOptions] = useState<DomainOption[]>([]);

  const adminQuery = useQuery({ queryKey: ["domains"], queryFn: fetchDomains, staleTime: 10000, retry: false });

  useEffect(() => {
    if (adminQuery.data?.domains?.length) {
      setOptions(adminQuery.data.domains.map((d) => ({ domain: d.domain, label: d.display_name || d.domain })));
    } else {
      // Fallback to stored domain if no admin rights
      const stored = localStorage.getItem("hydra_domain");
      setOptions(stored ? [{ domain: stored, label: stored }] : []);
    }
  }, [adminQuery.data]);

  return options;
}
