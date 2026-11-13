"""Install the v2.1a explicit-token DW page origin recorder into a build copy."""
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent


def _replace(text, before, after):
    if text.count(before) != 1:
        raise ValueError("DW origin anchor changed: " + before[:90])
    return text.replace(before, after, 1)


WRAPPERS = (
    "\n__attribute__((noinline)) void\n"
    "vm_page_free_list(vm_page_t freeq, boolean_t prepare_object)\n"
    "{\n"
    "\tk70_free_list_impl(freeq, prepare_object,\n"
    "\t    (uintptr_t)__builtin_return_address(0), NULL);\n"
    "}\n"
    "\n"
    "__attribute__((noinline)) void\n"
    "k70_vm_page_free_list_origin(vm_page_t freeq, boolean_t prepare_object,\n"
    "    struct k70_dw_token *tok)\n"
    "{\n"
    "\tk70_free_list_impl(freeq, prepare_object,\n"
    "\t    (uintptr_t)__builtin_return_address(0), tok);\n"
    "}\n"
)

DIAG_WRAPPER = (
    "__attribute__((noinline)) void\nk70_pmap_assert_free_from_list_diag(uint32_t ppnum, uintptr_t free_caller,\n"
    "    const struct k70_dw_snapshot *snap)\n{\n"
    "\tpmap_assert_free_recorded(ppnum, (uintptr_t)__builtin_return_address(0),\n"
    "\t    free_caller, snap);\n}\n"
)


def install(root):
    for name in ("K70DwOrigin.h",):
        shutil.copy2(HERE / name, root / "pexpert/arm" / name)
        shutil.copy2(HERE / name, root / "osfmk/kern" / name)
    shutil.copy2(HERE / "K70DwOrigin.c", root / "pexpert/arm" / "K70DwOrigin.c")
    mk = root / "osfmk/kern/Makefile"
    mtext = mk.read_text()
    if "K70DwOrigin.h" not in mtext:
        mtext = _replace(mtext, "\tK70Flight.h \\\n",
                         "\tK70Flight.h \\\n\tK70DwOrigin.h \\\n")
        mk.write_text(mtext)

    path = root / "pexpert/arm/k70_formal_diag.c"
    text = path.read_text()
    text = _replace(text, '#include "K70FlightKernel.c"\n',
                    '#include "K70FlightKernel.c"\n#include "K70DwOrigin.c"\n')
    path.write_text(text)

    path = root / "osfmk/vm/vm_resident.c"
    text = path.read_text()
    text = _replace(text, "#include <kern/K70Flight.h>\n",
                    "#include <kern/K70Flight.h>\n#include <kern/K70DwOrigin.h>\n#include <kern/thread.h>\n")
    text = _replace(
        text,
        "\nvoid\nvm_page_free_list(\n\tvm_page_t       freeq,\n\tboolean_t       prepare_object)\n{",
        "\nstatic __attribute__((noinline)) void\nk70_free_list_impl(\n"
        "\tvm_page_t       freeq,\n\tboolean_t       prepare_object,\n"
        "\tuintptr_t       k70_free_caller,\n\tstruct k70_dw_token *k70_tok)\n{")
    text = _replace(
        text,
        "#if MACH_ASSERT\n"
        "\t\t\t\tk70_pmap_assert_free_from_list(VM_PAGE_GET_PHYS_PAGE(mem),\n"
        "\t\t\t\t    (uintptr_t)__builtin_return_address(0));\n"
        "#endif\n",
        "#if MACH_ASSERT\n"
        "\t\t\t\t{\n"
        "\t\t\t\t\tstruct k70_dw_snapshot k70_dw_snap;\n"
        "\t\t\t\t\t(void)k70_dw_lookup(k70_tok, (uintptr_t)mem,\n"
        "\t\t\t\t\t    VM_PAGE_GET_PHYS_PAGE(mem), (uintptr_t)current_thread(), &k70_dw_snap);\n"
        "\t\t\t\t\tk70_pmap_assert_free_from_list_diag(VM_PAGE_GET_PHYS_PAGE(mem),\n"
        "\t\t\t\t\t    k70_free_caller, &k70_dw_snap);\n"
        "\t\t\t\t}\n"
        "#endif\n")
    text = _replace(text, "\nvoid\nvm_page_do_delayed_work(",
                    "\n__attribute__((noinline)) void\nvm_page_do_delayed_work(")
    marker = "\n__attribute__((noinline)) void\nvm_page_do_delayed_work("
    pos = text.index(marker)
    text = text[:pos] + WRAPPERS + text[pos:]
    text = _replace(
        text,
        "\tvm_page_t       local_free_q = VM_PAGE_NULL;\n",
        "\tvm_page_t       local_free_q = VM_PAGE_NULL;\n"
        "\tstruct k70_dw_token k70_dw_tok;\n"
        "\n"
        "\tk70_dw_try_begin((uintptr_t)current_thread(), (uintptr_t)object,\n"
        "\t    (uintptr_t)__builtin_return_address(0), dw_count, &k70_dw_tok);\n")
    text = _replace(
        text,
        "\t\tif (dwp->dw_mask & DW_vm_page_free) {\n"
        "\t\t\tvm_page_free_prepare_queues(m);\n",
        "\t\tif (dwp->dw_mask & DW_vm_page_free) {\n"
        "\t\t\tk70_dw_note(&k70_dw_tok, (uintptr_t)m,\n"
        "\t\t\t    (uintptr_t)VM_PAGE_OBJECT(m), (uint64_t)m->vmp_offset,\n"
        "\t\t\t    VM_PAGE_GET_PHYS_PAGE(m), dwp->dw_mask, (uint32_t)j,\n"
        "\t\t\t    m->vmp_wire_count,\n"
        "\t\t\t    (uint32_t)((m->vmp_busy ? K70_DW_PF_BUSY : 0) |\n"
        "\t\t\t        (m->vmp_fictitious ? K70_DW_PF_FICTITIOUS : 0) |\n"
        "\t\t\t        (m->vmp_dirty ? K70_DW_PF_DIRTY : 0) |\n"
        "\t\t\t        (m->vmp_pmapped ? K70_DW_PF_PMAPPED : 0) |\n"
        "\t\t\t        (m->vmp_wpmapped ? K70_DW_PF_WPMAPPED : 0) |\n"
        "\t\t\t        (m->vmp_wire_count != 0 ? K70_DW_PF_WIRED : 0) |\n"
        "\t\t\t        (m->vmp_lopage ? K70_DW_PF_LOPAGE : 0) |\n"
        "\t\t\t        (m->vmp_private ? K70_DW_PF_PRIVATE : 0)),\n"
        "\t\t\t    K70_DW_PF_KNOWN);\n"
        "\t\t\tvm_page_free_prepare_queues(m);\n")
    text = _replace(
        text,
        "\tif (local_free_q) {\n\t\tvm_page_free_list(local_free_q, TRUE);\n\t}\n",
        "\tif (local_free_q) {\n"
        "\t\tk70_vm_page_free_list_origin(local_free_q, TRUE, &k70_dw_tok);\n"
        "\t}\n"
        "\tk70_dw_end(&k70_dw_tok);\n")
    path.write_text(text)

    path = root / "osfmk/arm/pmap/pmap.c"
    text = path.read_text()
    text = _replace(text, "#include <kern/K70Flight.h>\n",
                    "#include <kern/K70Flight.h>\n#include <kern/K70DwOrigin.h>\n")
    text = _replace(
        text,
        "pmap_assert_free_recorded(ppnum_t ppnum, uintptr_t caller, uintptr_t free_caller)\n{",
        "pmap_assert_free_recorded(ppnum_t ppnum, uintptr_t caller, uintptr_t free_caller,\n"
        "    const struct k70_dw_snapshot *snap)\n{")
    text = _replace(text, "\t\t    free_caller, va_base_field);",
                    "\t\t    free_caller, va_base_field, snap);")
    text = _replace(text,
                    "\tpmap_assert_free_recorded(ppnum, (uintptr_t)__builtin_return_address(0), 0);",
                    "\tpmap_assert_free_recorded(ppnum, (uintptr_t)__builtin_return_address(0), 0, NULL);")
    text = _replace(
        text,
        "void\nk70_pmap_assert_free_from_list(uint32_t ppnum, uintptr_t free_caller)\n{\n"
        "\tpmap_assert_free_recorded(ppnum, (uintptr_t)__builtin_return_address(0), free_caller);\n}\n",
        "void\nk70_pmap_assert_free_from_list(uint32_t ppnum, uintptr_t free_caller)\n{\n"
        "\tpmap_assert_free_recorded(ppnum, (uintptr_t)__builtin_return_address(0),\n"
        "\t    free_caller, NULL);\n}\n\n" + DIAG_WRAPPER)
    path.write_text(text)
