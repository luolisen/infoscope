import { useMutation, useQueryClient } from "@tanstack/react-query";

import { archiveQueryKey, searchQueryKey, setEventSaved } from "../../api/archiveSearch";
import { eventDetailQueryKey } from "../../api/events";
import { nowQueryKey } from "../../api/now";

type SaveButtonProps = { eventId: string; saved: boolean; onSaved?: () => void };

export function SaveButton({ eventId, saved, onSaved }: SaveButtonProps) {
  const queryClient = useQueryClient();
  const mutation = useMutation({ mutationFn: () => setEventSaved(eventId, !saved) });

  function toggle() {
    mutation.mutate(undefined, {
      onSuccess: () => {
        void queryClient.invalidateQueries({ queryKey: nowQueryKey });
        void queryClient.invalidateQueries({ queryKey: eventDetailQueryKey(eventId) });
        void queryClient.invalidateQueries({ queryKey: archiveQueryKey(null).slice(0, 1) });
        void queryClient.invalidateQueries({ queryKey: searchQueryKey("", null).slice(0, 2) });
        onSaved?.();
      },
    });
  }

  return <span className="save-control"><button className="text-button" disabled={mutation.isPending} onClick={toggle} type="button">{mutation.isPending ? "Updating…" : saved ? "Remove saved" : "Save event"}</button>{mutation.isError && <span className="auth-error" role="alert">Could not update saved state.</span>}</span>;
}
