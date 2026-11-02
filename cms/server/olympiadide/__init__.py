# SPDX-License-Identifier: AGPL-3.0-or-later

"""Optional native Olympiad IDE integration for CMS.

The private ASGI runtime has a separate environment. Import service/handlers
explicitly so importing receipt models never initializes a web server.
"""
