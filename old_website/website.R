library(tidyverse)
library(highcharter)
library(shiny)
library(DT)
library(ggplot2)
library(scales) 

ui <- fluidPage(
  tags$head(
    tags$style(HTML("
      @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;800&display=swap');

      body {
        margin: 0;
        background: rgba(18,18,18,255);
        font-family: 'Inter', system-ui, -apple-system, 'Segoe UI', Roboto, Arial, sans-serif;
        color: whitesmoke;
      }

      .container-fluid { padding: 0; }

      .main-container {
        display: flex;
        flex-direction: column;
        align-items: center;
        min-height: 100vh;
      }

      .main-container h1 { 
        font-size: clamp(30px, 6vw, 70px);
        margin-top: 5vh;
        margin-bottom: 0;
        font-weight: 800; 
      }

      .navbar-parent {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 16px 5vw;
        width: 100%;
        border-bottom: 2px solid rgba(255,255,255,0.06);
        background: rgba(15,23,37,0.6);
        backdrop-filter: blur(6px);
        box-sizing: border-box;
      }

      .navbar-child {
        display: flex;
        gap: 20px;
        align-items: center;
      }

      .navbar-child a {
        margin: 0;
        color: whitesmoke;
        font-weight: bold;
        text-decoration: none;
        opacity: 0.9;
        transition: all 0.25s;
      }

      .navbar-child a:hover { transform: scale(1.1); }

      .typed-prefix { font-size: clamp(12px, 2.5vw,28px); font-weight: bold; color: #007bff; }
      .typed-suffix { 
        color:#ffffff; border-right:2px solid #cfe6ff; padding-right:2px;
        display:inline-block; animation: blink 0.75s step-end infinite; font-size: clamp(12px, 2.5vw, 28px); 
      }
      @keyframes blink { 50% { border-color: transparent; } }

      /* ----------------- Visual Parent & Cards ----------------- */
      .visual-parent {
        display: flex;
        flex-wrap: wrap;
        justify-content: center;
        align-items: flex-start;
        gap: 2rem;
        margin-top: 10vh;
        width: 90%;
        max-width: 1200px;
        margin-left: auto;
        margin-right: auto;
      }

      .visual-card {
        flex: 1 1 300px;        
        max-width: 600px;       
        height: 350px;          
        border: 2px solid #007bff;
        border-radius: 12px;
        overflow: hidden;
        position: relative;
        display: flex;
        transition: all 0.3s ease;
        background: rgba(15, 23, 37, 0.8);
      }

      .visual-card:hover { 
        box-shadow: 0px 0px 15px #007bff; 
        transform: scale(1.03); 
      }

      .visual-card .data,
      .visual-card .visual {
        position: absolute;
        top: 0; left: 0;
        width: 100%; height: 100%;
        display: flex;
        justify-content: center;
        align-items: center;
        padding: 10px;
        box-sizing: border-box;
        transition: opacity 0.25s;
      }

      .visual-card .visual { opacity: 0; }
      .visual-card:hover .data { opacity: 0; }
      .visual-card:hover .visual { opacity: 1; }

      .visual-card .data .dataTables_wrapper,
      .visual-card .visual canvas {
        width: 100% !important;
        height: 100% !important;
      }

      .visual-card table {
        font-size: 0.9rem;
      }

      /* Text card styling */
      .text-card {
        flex: 1 1 auto;
        max-width: 450px;
        min-width: 250px;
        padding: 20px 10px;
        border-radius: 10px;
        display: flex;
        flex-direction: row;
        justify-content: flex-start;
        align-items: flex-start;
        height: 100%;
      }

      .text-card h1 {
        font-size: clamp(28px, 4vw, 38px);
        margin-bottom: 0.5rem;
      }

      .text-card h2 {
        font-size: clamp(14px, 3vw, 22px);
        font-weight: 400;
        color: #d7e3f5;
      }

      /* Responsive stacking */
      @media (max-width: 768px) {
        .visual-parent {
          flex-direction: column;
          gap: 1.5rem;
          width: 95%;
        }
        .visual-card {
          width: 100%;
          max-width: 100%;
          height: 300px;
        }
        .text-card {
          width: 100%;
          max-width: 100%;
          padding: 15px;
        }
      }
      
      .services {
        position: relative;   /* allow pseudo-elements to position */
        overflow: hidden;
        white-space: nowrap;
        width: 80vw;
        margin: auto;
        margin-top: 10vh;
      }
      
            .services-track {
        display: inline-flex;
        animation: scroll 50s linear infinite;
            }
      
      .services-track img {
        margin: 0 30px;
      }
      
          @keyframes scroll {
        0%   { transform: translateX(0); }
        100% { transform: translateX(-50%); }
          }
      
           .services::before,
      .services::after {
        content: '';
        position: absolute;
        top: 0;
        width: 80px; 
        height: 100%;
        z-index: 2;
      }
      
            .services::before {
        left: 0;
        background: linear-gradient(to right, rgba(18,18,18,255); 0%, transparent 100%);
      }

      .services::after {
        right: 0;
        background: linear-gradient(to left, rgba(18,18,18,255); 0%, transparent 100%);
      }
    "))
  ),
  
  # Typed line script
  tags$script(HTML("
    document.addEventListener('DOMContentLoaded', function() {
      const typedEl = document.getElementById('typed-suffix');
      if (!typedEl) return;
      const phrases = ['students are the priority.', 'data security matters.', 'every student counts.', 'data empowers learning.'];
      const speed = { type: 80, del: 70, pauseAfter: 2000, pauseBefore: 1000 };
      let i = 0, j = 0, deleting = false;
      function tick() {
        const current = phrases[i % phrases.length];
        if (!deleting) { 
          typedEl.textContent = current.slice(0, j + 1); 
          j++; 
          if (j === current.length) { deleting = true; setTimeout(tick, speed.pauseAfter); return; } 
        } else { 
          typedEl.textContent = current.slice(0, j - 1); 
          j--; 
          if (j === 0) { deleting = false; i++; setTimeout(tick, speed.pauseBefore); return; } 
        }
        setTimeout(tick, deleting ? speed.del : speed.type);
      }
      const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)');
      if (!prefersReduced.matches) tick();
      else typedEl.textContent = phrases[0];
    });
  ")),
  
  div(
    class = "main-container",
    
    # Navbar
    div(
      class = "navbar-parent",
      div(class = "navbar-child",
          tags$a(href = "/", tags$img(src = "logo_light_2.png", height = "32px")),
          tags$a(href = "/", "Services"),
          tags$a(href = "/", "Contact")
      ),
      div(class = "navbar-child", tags$a(href = "/", "Client Portal"))
    ),
    
    # Title + typed line
    div(
      h1("Miranda Insights LLC"),
      div(class = "typed-line",
          span(class="typed-prefix", HTML("Where&nbsp;")),
          span(id="typed-suffix", class="typed-suffix", `aria-live`="polite")
      )
    ),
    
    # Visual cards
    div(
      class = "visual-parent",
      
      # Text card
      div(
        class = "text-card",
        h1("We make your data simple, beautiful and actionable.")
        
      ),
      
      # Example card with DT and plot
      div(
        class = "visual-card",
        div(class = "data", DTOutput("sankey_dt")),
        div(class = "visual", highchartOutput("sankey_plot", width = "100%", height = "100%"))
      )
    ),
    
    # Caresoul card
    div(
      class = "services",
      
      div(
        class = "services-track",
        
        tags$img(src = "service_1.png"),
        tags$img(src = "service_2.png"),
        tags$img(src = "service_3.png"),
        tags$img(src = "service_4.png"),
        tags$img(src = "service_5.png"),
        tags$img(src = "service_6.png"),
        tags$img(src = "service_7.png"),
        tags$img(src = "service_1.png"),
        tags$img(src = "service_2.png"),
        tags$img(src = "service_3.png"),
        tags$img(src = "service_4.png"),
        tags$img(src = "service_5.png"),
        tags$img(src = "service_6.png"),
        tags$img(src = "service_7.png")
      )
    ),
    
    # Service description
    div(
      style = "display: flex; justify-content: space-between; width: 80vw;",
      
      div(
        style = "width: 300px; height: 500px; border: solid whitesmoke; border-radius: 10px; display: flex; flex-direction: column; align-items: flex-start; padding: 15px;",
        h2("Interactive Dashboards"),
        p("test")
      ),
      div(
        style = "width: 300px; height: 500px; border: solid whitesmoke; border-radius: 10px;"
      ),
      div(
        style = "width: 300px; height: 500px; border: solid whitesmoke; border-radius: 10px;"
      ),
      div(
        style = "width: 300px; height: 500px; border: solid whitesmoke; border-radius: 10px;"
      )
    )
  )
)

server <- function(input, output, session) {
  
  # Generate sankey data
  sankey_data <- reactive({
    campuses <- c("North HS", "East HS", "West HS")
    scores <- c("Above Standard", "Near Standard", "Below Standard")
    
    expand.grid(Campus = campuses, Score = scores) %>%
      mutate(Count = sample(20:100, n(), replace = TRUE))
  })
  
  # Sankey datatable output
  output$sankey_dt <- renderDT({
    data <- sankey_data()
    
    datatable(
      data,
      rownames = FALSE,
      options = list(
        dom = 't', 
        paging = FALSE,
        initComplete = JS(
          "function(settings, json) {",
          "$(this.api().table().header()).css({'color': '#ffffff', 'font-weight': 'bold'});",
          "}"
        )
      )
    ) %>%
      formatStyle(
        names(data),
        color = "#f5f5f5"  # cell text color
      )
  })
  
  
  # Sankey visual output
  output$sankey_plot <- renderHighchart({
    data <- sankey_data()
    links <- data %>%
      transmute(from = Campus, to = Score, weight = Count)
    
    score_colors <- c(
      "Above Standard" = "#37b526",
      "Near Standard"  = "#d4d12a",
      "Below Standard" = "#eb4034"
    )
    
    school_colors <- c(
      "North HS" = "#007bff",
      "East HS"  = "#00bfff",
      "West HS"  = "#3399ff"
    )
    
    nodes <- data.frame(
      id = c(unique(data$Campus), unique(data$Score)),
      name = c(unique(data$Campus), unique(data$Score)),
      color = c(school_colors, score_colors)
    )
    
    highchart() %>%
      hc_chart(type = "sankey") %>%
      hc_title(
        text = "Student Performance by Campus",
        style = list(
          color = "#ffffff",
          fontWeight = "bold",
          fontSize = "18px"
        )
      ) %>%
      hc_plotOptions(
        series = list(
          dataLabels = list(
            color = "#ffffff",
            style = list(
              fontWeight = "bold",
              fontSize = "10px"
            )
          )
        )
      ) %>%
      hc_series(
        list(
          keys = c("from", "to", "weight"),
          data = list_parse(links),
          nodes = list_parse(nodes),
          name = "Number of Students"
        )
      ) %>%
      hc_tooltip(pointFormat = "{point.from} → {point.to}: {point.weight} students")
  })
}

shinyApp(ui, server)
