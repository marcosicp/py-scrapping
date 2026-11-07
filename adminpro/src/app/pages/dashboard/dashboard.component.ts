import { Component, OnInit, ViewChild } from '@angular/core';
import { AgGridAngular } from 'ag-grid-angular';
import { ColDef, GridApi, GridReadyEvent } from 'ag-grid-community';
import { Observable } from 'rxjs';
import { AppService } from 'src/app/service/app.service';
import { TotalValueRenderer } from './cellRender';
import { ChainEntry, chainTotal, formatAmount, toggleOffer } from './selection';

@Component({
  selector: 'app-dashboard',
  standalone: false,
  templateUrl: './dashboard.component.html',
  styleUrls: ['./dashboard.component.css'],
})
export class DashboardComponent implements OnInit {
  items?: any;
  noRowsTemplate = '¡Agrega tus productos!';
  itemsCarre?: ChainEntry[] = [];
  itemsDisco?: ChainEntry[] = [];
  itemsMami?: ChainEntry[] = [];
  itemsHiper?: ChainEntry[] = [];
  // -- D-15: one total per list, derived from that list and rendered under its
  // grid; the legacy setPinnedBottomRowData route is gone
  totalCarre = 0;
  totalDisco = 0;
  totalMami = 0;
  totalHiper = 0;
  rowDataClicked1 = {};
  public rowSelection: 'single' | 'multiple' = 'multiple';
  // Each Column Definition results in one Column.
  // -- Master grid: one canonical row per product, one price column per chain
  public columnDefs: ColDef[] = [
    {
      headerName: '',
      flex: 0,
      sortable: true,
      filter: true,
      cellStyle: { textAlign: 'center' },
      cellRenderer: TotalValueRenderer,
      cellRendererParams: {
        clicked: (data: any) => {
          data.selected = !data.selected;
          this.addItemToList(data);
        },
      },
    },
    {
      field: 'name',
      headerName: 'Producto',
      sortable: true,
      filter: true,
      suppressSizeToFit: true,
      flex: 2,
    },
    {
      field: 'unidad',
      headerName: 'Presentación',
      sortable: true,
      filter: true,
      suppressSizeToFit: true,
      flex: 1,
    },
    {
      field: 'brand',
      headerName: 'Marca',
      sortable: true,
      filter: true,
      suppressSizeToFit: true,
      flex: 1,
    },
    {
      field: 'offers.carre.price',
      headerName: 'Carrefour',
      sortable: true,
      filter: true,
      suppressSizeToFit: true,
      cellRenderer: (param: any) => {
        return param.value == null ? '' : '$' + param.value;
      },
      flex: 1,
    },
    {
      field: 'offers.disco.price',
      headerName: 'Disco',
      sortable: true,
      filter: true,
      suppressSizeToFit: true,
      cellRenderer: (param: any) => {
        return param.value == null ? '' : '$' + param.value;
      },
      flex: 1,
    },
    {
      field: 'offers.mami.price',
      headerName: 'SuperMami',
      sortable: true,
      filter: true,
      suppressSizeToFit: true,
      cellRenderer: (param: any) => {
        return param.value == null ? '' : '$' + param.value;
      },
      flex: 1,
    },
    {
      field: 'offers.hiper.price',
      headerName: 'La Anónima',
      sortable: true,
      filter: true,
      suppressSizeToFit: true,
      cellRenderer: (param: any) => {
        return param.value == null ? '' : '$' + param.value;
      },
      flex: 1,
    },
  ];

  public columnDefsGeneric: ColDef[] = [
    {
      field: 'name',
      suppressSizeToFit: true,
      flex: 2,
      headerName: 'Nombre',
      cellStyle: { fontSize: '11px' },
    },
    {
      field: 'presentation',
      headerName: 'Presentación',
      cellStyle: { fontSize: '11px' },
      suppressSizeToFit: true,
      flex: 1,
    },
    {
      field: 'price',
      headerName: 'Precio',
      cellStyle: { fontSize: '11px' },
      cellRenderer: (param: any) => {
        return param.value == null ? '' : '$' + param.value;
      },
      suppressSizeToFit: true,
      flex: 1,
    },
  ];

  // DefaultColDef sets props common to all Columns
  public defaultColDef: ColDef = {
    sortable: true,
    filter: true,
  };

  // Data that gets displayed in the grid
  public rowData$!: Observable<any>;
  private gridApi!: GridApi;

  constructor(private http: AppService) {}

  @ViewChild(AgGridAngular) agGrid!: AgGridAngular;

  ngOnInit() {
    this.http.getExams().subscribe((a) => {
      this.items = a;
    });
  }

  // Example load data from server
  onGridReady(params: GridReadyEvent) {
    this.gridApi = params.api;
  }

  onFilterTextBoxChanged() {
    this.gridApi.setGridOption('quickFilterText',
      (document.getElementById('filter-text-box') as HTMLInputElement).value
    );
  }

  /** Template helper: one chain list total, rendered under its grid (D-15). */
  formatMoney(value: number) {
    return formatAmount(value);
  }

  // -- D-1/D-10: selecting a canonical row adds EVERY present offer to its own
  // chain list ({id, name, presentation, price} of that offer); deselecting
  // removes them. The entry identity is the canonical row id, never the offer
  // name: one chain can show two presentations under the same name (SuperMami
  // stores every Cañuelas presentation as "ACEITE DE GIRASOL CAÑUELAS X .").
  // The presentation is the row's `unidad`, the only place that size exists
  // (D-14).
  addItemToList(data: any) {
    const offers = data.offers || {};
    const rowId: string = data.id;
    const presentation: string = data.unidad || '';

    // -- Carrefour
    if (offers.carre) {
      this.itemsCarre = toggleOffer(rowId, offers.carre, presentation, data.selected, this.itemsCarre);
      this.totalCarre = chainTotal(this.itemsCarre);
    }
    // -- Disco
    if (offers.disco) {
      this.itemsDisco = toggleOffer(rowId, offers.disco, presentation, data.selected, this.itemsDisco);
      this.totalDisco = chainTotal(this.itemsDisco);
    }
    // -- SuperMami
    if (offers.mami) {
      this.itemsMami = toggleOffer(rowId, offers.mami, presentation, data.selected, this.itemsMami);
      this.totalMami = chainTotal(this.itemsMami);
    }
    // -- La Anónima
    if (offers.hiper) {
      this.itemsHiper = toggleOffer(rowId, offers.hiper, presentation, data.selected, this.itemsHiper);
      this.totalHiper = chainTotal(this.itemsHiper);
    }
  }
}
