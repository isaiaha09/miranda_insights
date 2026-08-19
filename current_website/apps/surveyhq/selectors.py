from django.db.models import Count, Q

from .models import Survey


def dashboard_surveys(params):
    queryset = Survey.objects.select_related("client", "project").annotate(response_total=Count("responses"))
    status = (params.get("status") or "").strip()
    client = (params.get("client") or "").strip()
    year = (params.get("year") or "").strip()
    month = (params.get("month") or "").strip()
    category = (params.get("category") or "").strip()
    query = (params.get("q") or "").strip()
    if status:
        queryset = queryset.filter(status=status)
    if client:
        queryset = queryset.filter(client_id=client)
    if year.isdigit():
        queryset = queryset.filter(reporting_year=int(year))
    if month.isdigit():
        queryset = queryset.filter(reporting_month=int(month))
    if category:
        queryset = queryset.filter(category=category)
    if query:
        search = (
            Q(title__icontains=query)
            | Q(client__organization_name__icontains=query)
            | Q(client__contact_name__icontains=query)
            | Q(client_name_snapshot__icontains=query)
        )
        if len(query) == 6:
            search |= Q(access_code__exact=query)
        queryset = queryset.filter(search)
    return queryset.order_by("-updated_at", "-reporting_year", "-reporting_month", "title")


def dashboard_counts():
    counts = {status: 0 for status, _label in Survey.Status.choices}
    for row in Survey.objects.values("status").annotate(total=Count("id")):
        counts[row["status"]] = row["total"]
    counts["responses"] = Survey.objects.aggregate(total=Count("responses"))["total"] or 0
    return counts
