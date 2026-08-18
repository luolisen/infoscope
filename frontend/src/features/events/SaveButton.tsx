import { useMutation, useQueryClient } from "@tanstack/react-query";

import { archiveQueryKey, searchQueryKey, setEventSaved } from "../../api/archiveSearch";
import { eventDetailQueryKey } from "../../api/events";
import { nowQueryKey } from "../../api/now";
import { BookmarkIcon } from "../../components/Icons";

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

  return <span className="save-control"><button aria-label={saved ? "取消保存 Event" : "保存 Event"} aria-pressed={saved} className={`icon-button save-button${saved ? " save-button--saved" : ""}`} disabled={mutation.isPending} onClick={toggle} title={saved ? "取消保存" : "保存"} type="button"><BookmarkIcon className="action-icon" filled={saved} /></button>{mutation.isError && <span className="auth-error" role="alert">无法更新保存状态。</span>}</span>;
}
