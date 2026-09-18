from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse

from app.core.dependencies import CurrentUserDep, get_certificates_service, require_role
from app.core.http import read_body, wants_json
from app.core.templating import templates
from app.models import CertificateGenerateRequest, UserRole
from app.services.certificates_service import (
    CertificateTypeNotAllowedError,
    CertificatesService,
    EmployeeNotFoundError,
    LeaveNotEligibleError,
    NotAnInternError,
)

router = APIRouter(prefix="/certificates", tags=["certificates"])

_PAGE_SIZE_DEFAULT = 25


def _generation_error_response(request: Request, exc: Exception, current_user):
    if isinstance(exc, CertificateTypeNotAllowedError):
        status_code = status.HTTP_403_FORBIDDEN
        message = "Ce type d'attestation est réservé à l'administrateur."
    elif isinstance(exc, EmployeeNotFoundError):
        status_code = status.HTTP_404_NOT_FOUND
        message = "Employé introuvable."
    elif isinstance(exc, LeaveNotEligibleError):
        status_code = status.HTTP_409_CONFLICT
        message = "Ce congé n'est pas approuvé ou n'appartient pas à cet employé."
    else:  # NotAnInternError
        status_code = status.HTTP_400_BAD_REQUEST
        message = "Cet employé n'a pas un contrat de stage."

    if wants_json(request):
        raise HTTPException(status_code=status_code, detail=message) from exc
    return templates.TemplateResponse(
        request,
        "certificates/generate.html",
        {"current_user": current_user, "error": message},
        status_code=status_code,
    )


@router.get(
    "/generate", dependencies=[Depends(require_role(UserRole.ADMIN, UserRole.MANAGER))]
)
def generate_certificate_page(
    request: Request,
    current_user: CurrentUserDep,
    employee_id: Annotated[str | None, Query()] = None,
):
    return templates.TemplateResponse(
        request,
        "certificates/generate.html",
        {"current_user": current_user, "employee_id": employee_id, "error": None},
    )


@router.get("/my")
def list_my_certificates(
    request: Request,
    current_user: CurrentUserDep,
    service: Annotated[CertificatesService, Depends(get_certificates_service)],
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query()] = _PAGE_SIZE_DEFAULT,
):
    certificates = service.list_my(current_user, cursor_id=cursor, limit=limit)
    if wants_json(request):
        return certificates
    next_cursor = certificates[-1].id if len(certificates) == limit else None
    return templates.TemplateResponse(
        request,
        "certificates/list.html",
        {
            "current_user": current_user,
            "certificates": certificates,
            "next_cursor": next_cursor,
            "mine": True,
        },
    )


@router.get("", dependencies=[Depends(require_role(UserRole.ADMIN, UserRole.MANAGER))])
def list_certificates(
    request: Request,
    current_user: CurrentUserDep,
    service: Annotated[CertificatesService, Depends(get_certificates_service)],
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query()] = _PAGE_SIZE_DEFAULT,
):
    certificates = service.list_all(current_user, cursor_id=cursor, limit=limit)
    if wants_json(request):
        return certificates
    next_cursor = certificates[-1].id if len(certificates) == limit else None
    return templates.TemplateResponse(
        request,
        "certificates/list.html",
        {
            "current_user": current_user,
            "certificates": certificates,
            "next_cursor": next_cursor,
            "mine": False,
        },
    )


@router.post("")
async def create_certificate(
    request: Request,
    current_user: CurrentUserDep,
    service: Annotated[CertificatesService, Depends(get_certificates_service)],
):
    payload = await read_body(request, CertificateGenerateRequest)
    try:
        certificate = service.generate(current_user, payload)
    except (
        CertificateTypeNotAllowedError,
        EmployeeNotFoundError,
        LeaveNotEligibleError,
        NotAnInternError,
    ) as exc:
        return _generation_error_response(request, exc, current_user)

    if wants_json(request):
        return certificate
    return RedirectResponse(
        url=f"/certificates/{certificate.id}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.get("/{certificate_id}")
def certificate_detail(
    request: Request,
    certificate_id: str,
    current_user: CurrentUserDep,
    service: Annotated[CertificatesService, Depends(get_certificates_service)],
):
    certificate = service.get(current_user, certificate_id)
    if certificate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if wants_json(request):
        return certificate
    return templates.TemplateResponse(
        request,
        "certificates/detail.html",
        {"current_user": current_user, "certificate": certificate},
    )


@router.get("/{certificate_id}/download")
def download_certificate(
    certificate_id: str,
    current_user: CurrentUserDep,
    service: Annotated[CertificatesService, Depends(get_certificates_service)],
):
    certificate = service.get(current_user, certificate_id)
    if certificate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    pdf_bytes = service.render_pdf(certificate)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{certificate.number}.pdf"'},
    )
